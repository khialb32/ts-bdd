"""Command line for step 1: prove the PC can drive the strip over Bluetooth.

    python -m ambilight scan
    python -m ambilight test
    python -m ambilight color ff0000
"""

from __future__ import annotations

import argparse
import asyncio
import colorsys
import contextlib
import sys
import time

from bleak.exc import BleakError

from . import device, protocol
from .device import Found, LedStrip

NAMED_COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 100, 0),
    "purple": (128, 0, 255),
    "black": (0, 0, 0),
}


def parse_color(parts: list[str]) -> tuple[int, int, int]:
    """Accept "red", "ff0000", "#ff0000" or "255 0 0"."""
    if len(parts) == 3:
        rgb = tuple(int(p) for p in parts)
    elif len(parts) == 1 and parts[0].lower() in NAMED_COLORS:
        rgb = NAMED_COLORS[parts[0].lower()]
    elif len(parts) == 1:
        hex_ = parts[0].lstrip("#")
        if len(hex_) != 6:
            raise ValueError(f"not a color: {parts[0]!r}")
        rgb = tuple(int(hex_[i : i + 2], 16) for i in (0, 2, 4))
    else:
        raise ValueError(f"not a color: {' '.join(parts)!r}")
    if not all(0 <= c <= 255 for c in rgb):
        raise ValueError("color values must be 0-255")
    return rgb  # type: ignore[return-value]


def describe(found: Found) -> str:
    mark = "*" if found.is_candidate else " "
    return f"{mark} {found.rssi:>4} dBm  {found.address:<38} {found.name or '(no name)'}"


def signal(found: Found) -> str:
    return f"{found.rssi} dBm" if found.rssi is not None else "not seen in scan"


async def cmd_scan(args) -> int:
    print(f"Scanning for {args.timeout:g}s... (close LotusLanternX on your phone first)")
    found = await device.scan(args.timeout)
    shown = found if args.all else [f for f in found if f.is_candidate]
    if not shown:
        print("No LED controller found. Try 'scan --all' to list every Bluetooth device.")
        return 1
    print("  signal    address                                name")
    for f in shown:
        print(describe(f))
    if args.all:
        print("\n* = looks like a LotusLanternX-compatible controller")
    return 0


@contextlib.asynccontextmanager
async def connected(args, max_rate: float | None = None):
    """Resolve the device from the command line options and keep it connected."""
    found = await device.resolve(args.device, args.timeout)
    variant = protocol.VARIANTS[args.variant] if args.variant else None
    print(f"Connecting to {found.name or '(no name)'} [{found.address}]...")
    async with LedStrip(found, variant, with_response=args.with_response, max_rate=max_rate) as strip:
        print(
            f"Connected. Protocol variant: {strip.variant.key}, "
            f"characteristic {strip.char.uuid}, "
            f"{'write with response' if strip.with_response else 'write without response'}."
        )
        yield strip


async def cmd_inspect(args) -> int:
    found = await device.resolve(args.device, args.timeout)
    print(f"{found.name or '(no name)'} [{found.address}]  {signal(found)}")
    print(f"advertised services: {', '.join(found.service_uuids) or '-'}")
    print(f"guessed variant: {protocol.variant_for_name(found.name).key}\n")
    async with LedStrip(found) as strip:
        print(f"firmware id: {await strip.firmware_id()}\n")
        for service in strip.services:
            print(f"service {service.uuid}  {service.description}")
            for char in service.characteristics:
                chosen = "  <-- commands go here" if char.handle == strip.char.handle else ""
                print(f"    char {char.uuid}  handle={char.handle}  [{', '.join(char.properties)}]{chosen}")
    return 0


async def cmd_power(args) -> int:
    async with connected(args) as strip:
        await strip.power(args.command == "on")
    return 0


async def cmd_color(args) -> int:
    rgb = parse_color(args.color)
    async with connected(args) as strip:
        await strip.power(True)
        await strip.color(*rgb)
    return 0


async def cmd_brightness(args) -> int:
    async with connected(args) as strip:
        await strip.brightness(args.percent)
    return 0


async def cmd_test(args) -> int:
    """Walk through every basic command so the user can watch the strip respond."""
    async with connected(args) as strip:
        steps = [
            ("power on", lambda: strip.power(True)),
            ("red", lambda: strip.color(255, 0, 0)),
            ("green", lambda: strip.color(0, 255, 0)),
            ("blue", lambda: strip.color(0, 0, 255)),
            ("white", lambda: strip.color(255, 255, 255)),
            ("brightness 20%", lambda: strip.brightness(20)),
            ("brightness 100%", lambda: strip.brightness(100)),
            ("power off", lambda: strip.power(False)),
            ("power on", lambda: strip.power(True)),
        ]
        for label, step in steps:
            print(f"  -> {label}")
            await step()
            await asyncio.sleep(1.5)
        print("\nIf the strip followed every step, the PC can control it. Next: 'bench'.")
        print("If it did nothing, it speaks another dialect: run 'probe'.")
    return 0


async def cmd_bench(args) -> int:
    """Stream a rainbow as fast as asked and report the rate the link sustains.

    The controller is rated for about 20 updates per second; screen sync needs
    15-20 to look smooth. Ask for more with --fps to see where your unit gives up.
    """
    async with connected(args, max_rate=args.fps) as strip:
        await strip.power(True)
        await strip.brightness(100)
        interval = 1 / args.fps
        sent = 0
        start = time.perf_counter()
        next_at = start
        while (now := time.perf_counter()) - start < args.seconds:
            hue = ((now - start) / 3) % 1.0
            r, g, b = (round(c * 255) for c in colorsys.hsv_to_rgb(hue, 1, 1))
            await strip.stream_color(r, g, b)
            sent += 1
            next_at += interval
            await asyncio.sleep(max(0.0, next_at - time.perf_counter()))
        elapsed = time.perf_counter() - start
        print(f"Sent {sent} colors in {elapsed:.1f}s = {sent / elapsed:.1f} updates/s (asked for {args.fps:g}).")
        print("Did the rainbow look smooth? If it stuttered or lagged behind, try a lower --fps.")
    return 0


async def _blink(strip: LedStrip) -> None:
    while True:
        for rgb in ((255, 0, 0), (0, 0, 255)):
            await strip.color(*rgb)
            await asyncio.sleep(0.7)


async def cmd_probe(args) -> int:
    """Try each known protocol variant until the user sees the strip respond.

    The strip blinks red/blue with each candidate; a blink cannot be a color left over
    from an earlier attempt or from the phone app.
    """
    found = await device.resolve(args.device, args.timeout)
    guess = protocol.variant_for_name(found.name)
    order = [guess] + [v for v in protocol.VARIANTS.values() if v.key != guess.key]
    for variant in order:
        print(f"\nTrying variant '{variant.key}': {variant.description}")
        async with LedStrip(found, variant, with_response=args.with_response) as strip:
            for packet in protocol.WAKE_FRAMES:
                await strip.write(packet)
            await strip.power(True)
            blink = asyncio.create_task(_blink(strip))
            try:
                # input() blocks; keep the event loop (and the Bluetooth link) running meanwhile.
                answer = await asyncio.to_thread(input, "Is the strip blinking RED and BLUE? [y/N] ")
            finally:
                blink.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await blink
            if answer.strip().lower().startswith("y"):
                await strip.color(255, 255, 255)
                print(f"\nYour strip speaks variant '{variant.key}'. Add this to every command: --variant {variant.key}")
                return 0
    print("\nNo variant worked. Run 'inspect' and share the output so we can add support.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-d", "--device", help="address (MAC, or UUID on macOS) or name prefix; default: auto-pick")
    common.add_argument("-t", "--timeout", type=float, default=8.0, help="scan seconds (default 8)")
    common.add_argument("--variant", choices=sorted(protocol.VARIANTS), help="force a protocol variant")
    common.add_argument(
        "--with-response",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="force write with/without response (default: whatever the device supports, preferring without)",
    )

    parser = argparse.ArgumentParser(prog="python -m ambilight", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", parents=[common], help="list nearby LED controllers")
    p.add_argument("--all", action="store_true", help="list every Bluetooth device, not just controllers")
    p.set_defaults(func=cmd_scan)

    sub.add_parser("inspect", parents=[common], help="connect and print services/characteristics").set_defaults(
        func=cmd_inspect
    )
    sub.add_parser("on", parents=[common], help="turn the strip on").set_defaults(func=cmd_power)
    sub.add_parser("off", parents=[common], help="turn the strip off").set_defaults(func=cmd_power)

    p = sub.add_parser("color", parents=[common], help="set a color: red | ff0000 | 255 0 0")
    p.add_argument("color", nargs="+")
    p.set_defaults(func=cmd_color)

    p = sub.add_parser("brightness", parents=[common], help="set brightness 0-100")
    p.add_argument("percent", type=int, choices=range(0, 101), metavar="0-100")
    p.set_defaults(func=cmd_brightness)

    sub.add_parser("test", parents=[common], help="run every basic command, watch the strip").set_defaults(
        func=cmd_test
    )

    p = sub.add_parser("bench", parents=[common], help="stream a rainbow and measure updates/second")
    p.add_argument("--fps", type=float, default=20, help="target updates per second (default 20)")
    p.add_argument("--seconds", type=float, default=10, help="how long to run (default 10)")
    p.set_defaults(func=cmd_bench)

    sub.add_parser("probe", parents=[common], help="find which protocol variant your strip uses").set_defaults(
        func=cmd_probe
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except (LookupError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except BleakError as e:
        print(f"bluetooth error: {e}", file=sys.stderr)
        print(
            "Check that Bluetooth is on, the strip is powered, and LotusLanternX is fully "
            "closed on your phone (the strip accepts one connection at a time).",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130
