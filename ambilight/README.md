# ambilight

Turn a LotusLanternX LED strip into a backlight for your screen.

**Step 1 (this folder today):** control the strip from your PC's Bluetooth.
**Step 2 (next):** capture the outer 5% border of the screen and stream its color to the strip.

> These strips are *not* individually addressable: the controller drives the whole
> strip with one color at a time. The backlight will therefore show **one color**:
> the average of the screen's border, not a different color per edge.

## Setup

You need Python 3.10 or newer and a PC with Bluetooth Low Energy (almost every laptop;
on a desktop, any Bluetooth 4.0+ USB dongle).

```sh
cd ambilight
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

**Before every session: fully close LotusLanternX on your phone.** The controller
accepts a single connection; while the phone holds it, the PC cannot even see the strip.
If in doubt, turn Bluetooth off on the phone.

- **Windows:** nothing else to do. Do *not* pair the strip in Windows settings, it is
  not needed. Run from normal Windows, not WSL (WSL has no Bluetooth).
- **macOS:** the first run asks to let your terminal use Bluetooth; allow it
  (System Settings → Privacy & Security → Bluetooth). macOS shows a UUID instead of
  a MAC address; use that wherever an address is asked for.
- **Linux:** needs BlueZ (`bluetoothctl` working). If scanning fails with a permission
  error, add your user to the `bluetooth` group.

## Try it

```sh
python -m ambilight scan          # find the strip; look for ELK-BLEDOM or similar
python -m ambilight test          # on, red, green, blue, white, dim, off, on
python -m ambilight color orange  # also: ff8000, "#ff8000", 255 128 0
python -m ambilight brightness 40
python -m ambilight off
python -m ambilight bench         # streams a rainbow, reports updates/second
```

With one strip nearby, every command finds it by itself. With several, pick one with
`-d`, by address or name prefix: `-d BE:60:65:12:34:56` or `-d ELK`.

### If the strip does not react

1. `python -m ambilight scan --all`: if nothing marked `*` shows up, the phone is
   probably still connected, or the strip is out of range or unpowered.
2. `python -m ambilight probe`: tries each known dialect of the protocol and asks
   whether the strip turned red. When one works, pass it on from then on, for
   example `--variant legacy`.
3. `python -m ambilight inspect`: prints the firmware ID and every Bluetooth
   characteristic. Share that output if nothing works.

What to report back for step 2: the name `scan` shows, whether `test` worked, and the
updates/second `bench` reached with a smooth rainbow.

## How it talks to the strip

Every command is one 9-byte frame written, without response, to characteristic
`0000fff3-…` (service `fff0`). The controller never answers, so success is judged by
watching the strip. The frames come from the
[lotus-led](https://github.com/AlexMelanFromRingo/lotus-led) project, which transcribed
them from the official Lotus Lantern Android app.

| Command | Frame |
|---|---|
| power on / off | `7e 04 04 01 00 01 ff 00 ef` / `7e 04 04 00 00 00 ff 00 ef` |
| color | `7e 07 05 03 RR GG BB 10 ef` |
| color, streaming (screen sync) | `7e 07 05 03 RR GG BB 20 ef` |
| brightness 0-100 | `7e 04 01 LL ff ff ff 00 ef` |

Those are the `lotus` frames, the default. Controller firmwares differ, so three other
dialects are built in (byte tables in `ambilight/protocol.py`, taken from the
[elkbledom](https://github.com/dave-code-ruiz/elkbledom) Home Assistant integration).
The tool guesses from the advertised name; `probe` confirms it, and `--variant` forces it.

| Variant | Guessed for | Difference |
|---|---|---|
| `lotus` | ELK-BLEDOM, ELK-BLE, ELK-BTC, ELK-BULB, LEDBLE | the official app's frames |
| `legacy` | (only via `probe` / `--variant`) | older `7e 00 …` frames |
| `bledob` | ELK-BLEDOB, ELK-BLEDOM0E | `7e 07 …` frames, max 10 updates/s |
| `melk` | MELK-… | sends a login right after connecting, or the controller hangs up |

Writes are capped at 20 per second (10 for `bledob`), about what the controller's chip
handles before it starts dropping frames.

## Development

```sh
pip install -r requirements-dev.txt
python -m pytest
```

The tests use a fake Bluetooth client, so they run without a strip.
