"""Composable image filters, addressed by name.

Filters run on the full frame before slicing, so an effect like edge detection
stays continuous across key boundaries instead of restarting inside every tile.
Each filter takes and returns an RGB :class:`PIL.Image.Image`.

Names may carry a single numeric argument, e.g. ``posterize:3`` or ``pixelate:24``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PIL import Image, ImageFilter, ImageOps

Filter = Callable[[Image.Image, float | None], Image.Image]

_REGISTRY: dict[str, tuple[Filter, float, str]] = {}


def register(name: str, default: float = 0.0, doc: str = "") -> Callable[[Filter], Filter]:
    def decorator(fn: Filter) -> Filter:
        _REGISTRY[name] = (fn, default, doc or (fn.__doc__ or "").strip())
        return fn

    return decorator


def available() -> list[dict[str, object]]:
    """Filter catalogue, for the API and the web demo's control panel."""
    return [
        {"name": name, "default": default, "doc": doc}
        for name, (_, default, doc) in sorted(_REGISTRY.items())
    ]


@register("grayscale", doc="Desaturate to luminance.")
def _grayscale(img: Image.Image, _arg: float | None = None) -> Image.Image:
    return ImageOps.grayscale(img).convert("RGB")


@register("invert", doc="Photographic negative.")
def _invert(img: Image.Image, _arg: float | None = None) -> Image.Image:
    return ImageOps.invert(img.convert("RGB"))


@register("threshold", default=128, doc="Hard black/white cut at a luminance level.")
def _threshold(img: Image.Image, arg: float | None = None) -> Image.Image:
    level = int(arg if arg is not None else 128)
    gray = ImageOps.grayscale(img)
    return gray.point(lambda p: 255 if p >= level else 0).convert("RGB")


@register("posterize", default=3, doc="Reduce to N bits per channel (1-8).")
def _posterize(img: Image.Image, arg: float | None = None) -> Image.Image:
    bits = max(1, min(8, int(arg if arg is not None else 3)))
    return ImageOps.posterize(img.convert("RGB"), bits)


@register("pixelate", default=32, doc="Downsample to N pixels wide, then blow it back up.")
def _pixelate(img: Image.Image, arg: float | None = None) -> Image.Image:
    target = max(2, int(arg if arg is not None else 32))
    small = img.resize((target, max(1, round(target * img.height / img.width))), Image.Resampling.BILINEAR)
    return small.resize(img.size, Image.Resampling.NEAREST)


@register("edges", default=1, doc="Sobel-style edge detection.")
def _edges(img: Image.Image, arg: float | None = None) -> Image.Image:
    passes = max(1, min(4, int(arg if arg is not None else 1)))
    out = img.convert("RGB")
    for _ in range(passes):
        out = out.filter(ImageFilter.FIND_EDGES)
    return out


@register("blur", default=2, doc="Gaussian blur of radius N.")
def _blur(img: Image.Image, arg: float | None = None) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(float(arg if arg is not None else 2)))


@register("sharpen", default=2, doc="Unsharp mask.")
def _sharpen(img: Image.Image, arg: float | None = None) -> Image.Image:
    return img.filter(ImageFilter.UnsharpMask(radius=float(arg if arg is not None else 2)))


@register("contrast", default=1.6, doc="Multiply contrast by N.")
def _contrast(img: Image.Image, arg: float | None = None) -> Image.Image:
    from PIL import ImageEnhance

    return ImageEnhance.Contrast(img.convert("RGB")).enhance(float(arg if arg is not None else 1.6))


# A false-colour ramp: black -> deep blue -> magenta -> orange -> white.
_THERMAL_STOPS = [
    (0.00, (0, 0, 24)),
    (0.25, (60, 0, 130)),
    (0.50, (200, 30, 120)),
    (0.75, (250, 150, 30)),
    (1.00, (255, 255, 220)),
]


def _thermal_lut() -> list[int]:
    channels: list[list[int]] = [[], [], []]
    for value in range(256):
        t = value / 255
        for i in range(len(_THERMAL_STOPS) - 1):
            t0, c0 = _THERMAL_STOPS[i]
            t1, c1 = _THERMAL_STOPS[i + 1]
            if t0 <= t <= t1:
                k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                for ch in range(3):
                    channels[ch].append(round(c0[ch] + (c1[ch] - c0[ch]) * k))
                break
    return channels[0] + channels[1] + channels[2]


@register("thermal", doc="Map luminance onto a thermal-camera false-colour ramp.")
def _thermal(img: Image.Image, _arg: float | None = None) -> Image.Image:
    gray = ImageOps.grayscale(img)
    return gray.convert("RGB").point(_thermal_lut())


@register("scanlines", default=3, doc="CRT scanlines every N rows.")
def _scanlines(img: Image.Image, arg: float | None = None) -> Image.Image:
    period = max(2, int(arg if arg is not None else 3))
    out = img.convert("RGB").copy()
    pixels = out.load()
    for y in range(0, out.height, period):
        for x in range(out.width):
            r, g, b = pixels[x, y]
            pixels[x, y] = (r // 3, g // 3, b // 3)
    return out


def parse(spec: str) -> tuple[str, float | None]:
    """Split ``"posterize:3"`` into ``("posterize", 3.0)``."""
    name, _, raw = spec.partition(":")
    name = name.strip().lower()
    if not raw.strip():
        return name, None
    try:
        return name, float(raw)
    except ValueError as exc:
        raise ValueError(f"filter {name!r} got a non-numeric argument {raw!r}") from exc


def apply_chain(img: Image.Image, specs: Iterable[str]) -> Image.Image:
    """Run filters left to right. Unknown names raise rather than silently no-op."""
    out = img
    for spec in specs:
        if not spec.strip():
            continue
        name, arg = parse(spec)
        entry = _REGISTRY.get(name)
        if entry is None:
            raise KeyError(f"unknown filter {name!r}; known: {sorted(_REGISTRY)}")
        fn, default, _doc = entry
        out = fn(out, arg if arg is not None else (default or None))
    return out
