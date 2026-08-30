"""HTTP + WebSocket API around the pipeline.

The pipeline runs in a background thread and pushes tiles into a
:class:`~slicedeck.outputs.memory.MemorySink`. Clients hold a WebSocket that
tells them which keys changed on each frame and then fetch only those tiles, so
an idle scene costs almost no bandwidth.

Needs the optional dependency: ``pip install 'slicedeck[server]'``
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager, suppress
from io import BytesIO
from pathlib import Path

from .config import DECKS, Config
from .outputs import MemorySink
from .pipeline import Pipeline
from .sources import build_source

log = logging.getLogger("slicedeck.server")

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"

try:  # The API extra is optional; the CLI works without it.
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - exercised only without the extra
    BaseModel = None

if BaseModel is not None:
    # Request models must live at module scope. This module uses postponed
    # annotation evaluation, so FastAPI resolves a handler's annotations against
    # module globals; models defined inside create_app() are invisible there and
    # silently degrade into query parameters.

    class PressBody(BaseModel):
        row: int
        col: int

    class FiltersBody(BaseModel):
        filters: list[str] = []

    class DeckBody(BaseModel):
        deck: str


class Runner:
    """Owns the pipeline thread and broadcasts per-frame state to WebSocket clients."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.sink = MemorySink(quality=config.jpeg_quality)
        self.pipeline = Pipeline(config, build_source(config), [self.sink])
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="pipeline", daemon=True)
        self._clients: set[object] = set()
        self._loop_ref: asyncio.AbstractEventLoop | None = None
        self.last_state: dict[str, object] = {}

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop_ref = loop
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)
        self.pipeline.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.perf_counter()
            result = self.pipeline.process_frame_safe()
            if result is not None:
                self.last_state = {
                    "changed": [k for k, s in result.keys.items() if s.dirty],
                    "moving": result.moving_keys,
                    "scores": {str(k): round(s.score, 1) for k, s in result.keys.items()},
                    "areas": {str(k): round(s.area, 3) for k, s in result.keys.items()},
                    "zoom_depth": self.pipeline.zoom_depth,
                    "interpolated": self.pipeline.interpolated,
                    "frame": self.pipeline.metrics.frames,
                }
                self._broadcast(self.last_state)
            remaining = self.config.interval - (time.perf_counter() - started)
            if remaining > 0:
                self._stop.wait(remaining)

    def _broadcast(self, message: dict[str, object]) -> None:
        loop = self._loop_ref
        if loop is None or not self._clients:
            return
        for client in list(self._clients):
            with suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(self._send(client, message), loop)

    @staticmethod
    async def _send(client, message: dict[str, object]) -> None:
        with suppress(Exception):
            await client.send_json(message)

    def add_client(self, ws) -> None:
        self._clients.add(ws)

    def remove_client(self, ws) -> None:
        self._clients.discard(ws)


def create_app(config: Config):
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse, Response
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError("the API needs FastAPI: pip install 'slicedeck[server]'") from exc

    from . import filters as filter_registry

    runner = Runner(config)

    @asynccontextmanager
    async def lifespan(_app):
        runner.start(asyncio.get_running_loop())
        try:
            yield
        finally:
            runner.stop()

    app = FastAPI(title="slicedeck", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def _jpeg(image) -> Response:
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=config.jpeg_quality)
        return Response(buffer.getvalue(), media_type="image/jpeg")

    @app.get("/api/config")
    def get_config() -> JSONResponse:
        deck = runner.pipeline.config.deck
        return JSONResponse(
            {
                **runner.pipeline.config.redacted(),
                "deck_key": next((k for k, v in DECKS.items() if v.name == deck.name), "custom"),
                "decks": {
                    key: {"cols": spec.cols, "rows": spec.rows, "key_px": spec.key_px, "name": spec.name}
                    for key, spec in DECKS.items()
                },
                "source_label": runner.pipeline.source.label,
            }
        )

    @app.get("/api/filters")
    def get_filters() -> JSONResponse:
        return JSONResponse(filter_registry.available())

    @app.post("/api/filters")
    def set_filters(body: FiltersBody) -> JSONResponse:
        known = {entry["name"] for entry in filter_registry.available()}
        # Validate the whole chain before committing, so one bad name cannot
        # wedge the pipeline thread on its next frame.
        for spec in body.filters:
            try:
                name, _arg = filter_registry.parse(spec)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if name not in known:
                raise HTTPException(status_code=400, detail=f"unknown filter: {name}")
        runner.pipeline.set_filters(body.filters)
        return JSONResponse({"filters": body.filters})

    @app.post("/api/deck")
    def set_deck(body: DeckBody) -> JSONResponse:
        spec = DECKS.get(body.deck)
        if spec is None:
            raise HTTPException(status_code=400, detail=f"unknown deck: {body.deck}")
        runner.pipeline.reset_zoom()
        runner.pipeline.set_deck(spec)
        return JSONResponse({"deck": spec.name, "cols": spec.cols, "rows": spec.rows})

    @app.get("/api/state")
    def get_state() -> JSONResponse:
        return JSONResponse({**runner.last_state, "metrics": runner.pipeline.metrics.snapshot()})

    @app.get("/api/metrics")
    def get_metrics() -> JSONResponse:
        return JSONResponse(runner.pipeline.metrics.snapshot())

    @app.post("/api/press")
    def press(body: PressBody) -> JSONResponse:
        try:
            box = runner.pipeline.press(body.row, body.col)
        except (IndexError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(
            {
                "zoom_depth": runner.pipeline.zoom_depth,
                "interpolated": runner.pipeline.interpolated,
                "box": box.as_tuple(),
            }
        )

    @app.post("/api/back")
    def back() -> JSONResponse:
        box = runner.pipeline.back()
        return JSONResponse(
            {"zoom_depth": runner.pipeline.zoom_depth, "box": box.as_tuple() if box else None}
        )

    @app.post("/api/reset")
    def reset() -> JSONResponse:
        runner.pipeline.reset_zoom()
        return JSONResponse({"zoom_depth": 0})

    @app.get("/api/key/{key}.jpg")
    def key_image(key: int) -> Response:
        tile = runner.sink.get(key)
        if tile is None:
            raise HTTPException(status_code=404, detail=f"no tile for key {key} yet")
        return Response(
            tile.payload,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store", "X-Tile-Version": str(tile.version)},
        )

    @app.get("/api/preview.jpg")
    def preview() -> Response:
        return _jpeg(runner.pipeline.render_preview())

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        await ws.accept()
        runner.add_client(ws)
        try:
            while True:
                # Clients may drive the deck over the same socket.
                message = await ws.receive_json()
                action = message.get("action")
                if action == "press":
                    with suppress(IndexError, RuntimeError, KeyError, ValueError):
                        runner.pipeline.press(int(message["row"]), int(message["col"]))
                elif action == "back":
                    runner.pipeline.back()
                elif action == "reset":
                    runner.pipeline.reset_zoom()
        except WebSocketDisconnect:
            pass
        finally:
            runner.remove_client(ws)

    if WEB_ROOT.is_dir():
        app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")
    else:  # pragma: no cover - packaged install without the demo folder
        log.warning("web/ not found at %s; serving API only", WEB_ROOT)

    return app


def serve(config: Config) -> int:
    try:
        import uvicorn
    except ImportError:
        log.error("the API needs uvicorn: pip install 'slicedeck[server]'")
        return 2

    log.info("serving on http://%s:%d", config.host, config.port)
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level="warning")
    return 0
