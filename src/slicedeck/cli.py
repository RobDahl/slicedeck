"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from types import FrameType

from . import __version__
from . import filters as filter_registry
from .config import DECKS, load_config
from .outputs import FilesystemSink
from .pipeline import Pipeline
from .sources import build_source

log = logging.getLogger("slicedeck")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slicedeck",
        description="Split a live camera frame across the keys of a Stream Deck.",
    )
    parser.add_argument("--version", action="version", version=f"slicedeck {__version__}")
    parser.add_argument("--source", help="reolink | mjpeg | image_url | video_file | synthetic")
    parser.add_argument("--deck", choices=sorted(DECKS), help="Stream Deck model")
    parser.add_argument("--fps", type=float, help="frames per second")
    parser.add_argument(
        "--filter",
        action="append",
        default=None,
        metavar="NAME[:ARG]",
        help="filter to apply, repeatable and ordered (e.g. --filter thermal --filter edges)",
    )
    parser.add_argument("--output", help="directory for the JPEG tiles")
    parser.add_argument("--hid", action="store_true", help="push to Stream Deck hardware over USB")
    parser.add_argument("--serve", action="store_true", help="run the HTTP API instead of writing files")
    parser.add_argument("--port", type=int, help="port for --serve")
    parser.add_argument("--no-motion", action="store_true", help="disable motion and dirty-tile skipping")
    parser.add_argument("--list-filters", action="store_true", help="print available filters and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _apply_overrides(config, args):
    from dataclasses import replace

    updates: dict[str, object] = {}
    if args.source:
        updates["source"] = args.source
    if args.deck:
        updates["deck"] = DECKS[args.deck]
    if args.fps:
        updates["fps"] = args.fps
    if args.filter is not None:
        updates["filters"] = tuple(args.filter)
    if args.output:
        from pathlib import Path

        updates["output_dir"] = Path(args.output)
    if args.port:
        updates["port"] = args.port
    if args.no_motion:
        updates["motion"] = False
    return replace(config, **updates) if updates else config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_filters:
        for entry in filter_registry.available():
            default = f" (default {entry['default']:g})" if entry["default"] else ""
            print(f"  {entry['name']:<12}{entry['doc']}{default}")
        return 0

    config = _apply_overrides(load_config(), args)

    if args.serve:
        from .server import serve

        return serve(config)

    try:
        source = build_source(config)
    except (ValueError, RuntimeError) as exc:
        log.error("%s", exc)
        return 2

    sinks = [FilesystemSink(config.output_dir, quality=config.jpeg_quality)]
    if args.hid:
        from .outputs import HidDeckSink

        sinks.append(HidDeckSink())

    pipeline = Pipeline(config, source, sinks)
    log.info(
        "%s | %s | %dx%d keys @ %.1f fps%s",
        config.deck.name,
        source.label,
        config.deck.cols,
        config.deck.rows,
        config.fps,
        f" | filters: {', '.join(config.filters)}" if config.filters else "",
    )

    running = True

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    try:
        while running:
            started = time.perf_counter()
            pipeline.process_frame_safe()
            if pipeline.metrics.frames % 10 == 0 and pipeline.metrics.frames:
                log.info("%s", pipeline.metrics.summary_line())
            # Sleep only for the time the frame did not already consume.
            remaining = config.interval - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)
    finally:
        pipeline.close()
        log.info("stopped | %s", pipeline.metrics.summary_line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
