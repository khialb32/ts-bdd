"""Byte frames understood by ELK-BLEDOM family controllers (the LotusLanternX app's strips).

Every command is one 9-byte frame: 0x7E, seven payload bytes, 0xEF. The controller
drops anything else silently and never answers, so there is no way to ask it which
dialect it speaks: ``probe`` tries each one while the user watches the strip.

Sources: the "app" frames are what the Lotus Lantern Android app (wl.smartled, the
twin of the LotusLanternX iPhone app) sends, decompiled independently by lotus-led and
Rxflex/LotusLantern. "classic" is what most other open-source tools send. bledob comes
from 8none1/elk-bledob's Bluetooth captures, melk from the elkbledom Home Assistant
integration's per-model tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HEAD = 0x7E
TAIL = 0xEF


def frame(*payload: int) -> bytes:
    if len(payload) != 7:
        raise ValueError(f"a frame carries 7 payload bytes, got {len(payload)}")
    return bytes((HEAD, *payload, TAIL))


def _byte(value: int, name: str) -> int:
    if not 0 <= value <= 255:
        raise ValueError(f"{name} must be 0-255, got {value}")
    return value


def _percent(value: int) -> int:
    if not 0 <= value <= 100:
        raise ValueError(f"brightness must be 0-100, got {value}")
    return value


@dataclass(frozen=True)
class Variant:
    """One dialect of the protocol. Byte templates use R, G, B and L (level 0-100)."""

    key: str
    description: str
    name_prefixes: tuple[str, ...]
    power_on: bytes
    power_off: bytes
    color_template: tuple[int | str, ...]
    brightness_template: tuple[int | str, ...]
    # Same as color_template but tells the firmware a stream follows (music/screen
    # sync), so it does not restart its animation state on every write.
    stream_template: tuple[int | str, ...] | None = None
    # Raw writes sent right after connecting, each followed by a pause in seconds.
    init: tuple[tuple[bytes, float], ...] = field(default=())
    # Frames per second the controller takes before it starts dropping them.
    max_rate: float = 20.0

    def power(self, on: bool) -> bytes:
        return self.power_on if on else self.power_off

    def color(self, r: int, g: int, b: int) -> bytes:
        return _fill(self.color_template, R=_byte(r, "red"), G=_byte(g, "green"), B=_byte(b, "blue"))

    def stream_color(self, r: int, g: int, b: int) -> bytes:
        template = self.stream_template or self.color_template
        return _fill(template, R=_byte(r, "red"), G=_byte(g, "green"), B=_byte(b, "blue"))

    def brightness(self, percent: int) -> bytes:
        return _fill(self.brightness_template, L=_percent(percent))


def _fill(template: tuple[int | str, ...], **values: int) -> bytes:
    return frame(*(values[b] if isinstance(b, str) else b for b in template))


VARIANTS: dict[str, Variant] = {
    v.key: v
    for v in (
        Variant(
            key="app",
            description="the frames the LotusLanternX / Lotus Lantern app sends",
            name_prefixes=("ELK", "BLEDOM", "ELK-BLEDOM", "ELK_BLEDOM", "ELK-BLE", "ELK-BTC", "LEDBLE"),
            power_on=frame(0x04, 0x04, 0x01, 0x00, 0x01, 0xFF, 0x00),
            power_off=frame(0x04, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00),
            color_template=(0x07, 0x05, 0x03, "R", "G", "B", 0x10),
            stream_template=(0x07, 0x05, 0x03, "R", "G", "B", 0x20),
            brightness_template=(0x04, 0x01, "L", 0xFF, 0xFF, 0xFF, 0x00),
        ),
        Variant(
            key="classic",
            description="the frames most open-source ELK-BLEDOM tools send",
            name_prefixes=(),
            power_on=frame(0x00, 0x04, 0xF0, 0x00, 0x01, 0xFF, 0x00),
            power_off=frame(0x00, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00),
            color_template=(0x00, 0x05, 0x03, "R", "G", "B", 0x00),
            brightness_template=(0x00, 0x01, "L", 0x00, 0x00, 0x00, 0x00),
        ),
        Variant(
            key="bledob",
            description="ELK-BLEDOB / ELK-BLEDOM0E controllers",
            name_prefixes=("ELK-BLEDOB", "ELK-BLEDOM0E", "BLEDOB"),
            power_on=frame(0x07, 0x04, 0xFF, 0x00, 0x01, 0x02, 0x01),
            power_off=frame(0x07, 0x04, 0x00, 0x00, 0x00, 0x02, 0x01),
            # Trailer 0x10 as in 8none1/elk-bledob's captures of the vendor app; the
            # elkbledom table's 10 looks like that hex value copied as decimal.
            color_template=(0x07, 0x05, 0x03, "R", "G", "B", 0x10),
            brightness_template=(0x04, 0x01, "L", 0x01, 0xFF, 0x02, 0x01),
            # Drops a command that follows another too closely.
            max_rate=10.0,
        ),
        Variant(
            key="melk",
            description="MELK-* controllers, which hang up unless they get a login first",
            name_prefixes=("MELK", "MODELX"),
            power_on=frame(0x00, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00),
            power_off=frame(0x00, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00),
            color_template=(0x00, 0x05, 0x03, "R", "G", "B", 0x00),
            brightness_template=(0x04, 0x01, "L", 0xFF, 0x00, 0xFF, 0x00),
            init=((bytes((0x7E, 0x07, 0x83)), 1.0), (bytes((0x7E, 0x04, 0x04)), 1.0)),
        ),
    )
}

DEFAULT_VARIANT = VARIANTS["app"]

# Every power-on frame that means "on" whatever the dialect, so ``probe`` can light the
# strip before testing colors. MELK's power-on is left out: other firmwares read those
# same bytes as "off".
WAKE_FRAMES = tuple(VARIANTS[k].power_on for k in ("app", "classic", "bledob"))


def variant_for_name(name: str | None) -> Variant:
    """Best guess from the advertised name; ``probe`` confirms it on real hardware.

    The longest matching prefix wins, so "ELK-BLEDOB" is not taken for "ELK-BLE".
    """
    upper = (name or "").strip().upper()
    matches = [(len(p), v) for v in VARIANTS.values() for p in v.name_prefixes if upper.startswith(p)]
    if not matches:
        return DEFAULT_VARIANT
    return max(matches, key=lambda m: m[0])[1]


def matches_known_prefix(name: str) -> bool:
    upper = name.strip().upper()
    return any(upper.startswith(p) for v in VARIANTS.values() for p in v.name_prefixes)
