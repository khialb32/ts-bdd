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

**Windows** (install Python from [python.org](https://www.python.org/downloads/) and
tick "Add python.exe to PATH"). In a Command Prompt (`cmd`), not PowerShell:

```bat
cd ambilight
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

PowerShell refuses `activate` by default ("running scripts is disabled"); either use
`cmd`, or run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

**macOS / Linux:**

```sh
cd ambilight
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`python3 --version` must say 3.10 or newer. macOS's built-in `python3` is often 3.9:
install a newer one from python.org or with `brew install python`. On Debian/Ubuntu,
`python3 -m venv` needs `sudo apt install python3-venv` first.

Once the environment is active, `python` means the right interpreter on every OS, so
the commands below work as written. In a new terminal, activate it again first.

**Before every session: fully close LotusLanternX on your phone.** The controller
accepts a single connection; while the phone holds it, the PC cannot even see the strip.
If in doubt, turn Bluetooth off on the phone.

- **Windows:** nothing else to do. Do *not* pair the strip in Windows settings, it is
  not needed. Run from normal Windows, not WSL (WSL has no Bluetooth).
- **macOS:** the first run asks to let your terminal use Bluetooth; allow it
  (System Settings → Privacy & Security → Bluetooth). macOS shows a UUID instead of
  a MAC address; use that wherever an address is asked for.
- **Linux:** needs BlueZ (`bluetoothctl` working). If scanning fails with a permission
  error, add your user to the `bluetooth` group. If the strip vanishes after a crash,
  the PC may still hold the link: `bluetoothctl disconnect <address>`.

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
   probably still connected, or the strip is out of range or unpowered. Some strips
   advertise no name; on Windows/Linux the tool still spots their `BE:60:65:…`
   address, but on macOS it cannot. Look for a strong `(no name)` entry that
   disappears when you unplug the strip, and pass its address with `-d`.
2. `python -m ambilight probe`: tries each known dialect of the protocol, making the
   strip blink red and blue, and asks whether it does. When one works, add it to every
   command from then on, for example `--variant classic`.
3. `python -m ambilight inspect`: prints the firmware ID and every Bluetooth
   characteristic. Share that output if nothing works.

What to report back for step 2: the name `scan` shows, whether `test` worked, and the
updates/second `bench` reached with a smooth rainbow.

## How it talks to the strip

Every command is one 9-byte frame written, without response, to characteristic
`0000fff3-…` (service `fff0`). The controller never answers, so success is judged by
watching the strip. Firmwares differ in the exact bytes, so four dialects are built in;
byte tables are in `ambilight/protocol.py`. The tool guesses one from the advertised
name, `probe` confirms it on your strip, and `--variant` forces it.

| Variant | Guessed for | Color frame | Notes |
|---|---|---|---|
| `app` | ELK-BLEDOM and other ELK-…, LEDBLE | `7e 07 05 03 RR GG BB 10 ef` | default; exactly what the LotusLanternX app sends; has a streaming form (`… 20 ef`) for screen sync |
| `classic` | (via `probe` / `--variant`) | `7e 00 05 03 RR GG BB 00 ef` | what most open-source tools send |
| `bledob` | ELK-BLEDOB, ELK-BLEDOM0E | `7e 07 05 03 RR GG BB 10 ef` | `7e 07 …` power frames, max 10 updates/s |
| `melk` | MELK-… | `7e 00 05 03 RR GG BB 00 ef` | sends a login right after connecting, or the controller hangs up |

Sources: `app` is what the Android twin of LotusLanternX ("Lotus Lantern", `wl.smartled`)
sends, decompiled independently by
[lotus-led](https://github.com/AlexMelanFromRingo/lotus-led) and
[Rxflex/LotusLantern](https://github.com/Rxflex/LotusLantern). `classic` is what
[elkbledom](https://github.com/dave-code-ruiz/elkbledom) (Home Assistant),
[elk-led-controller](https://github.com/b1scoito/elk-led-controller),
[ELK-BLEDOM](https://github.com/FergusInLondon/ELK-BLEDOM) and
[bledom-qt](https://github.com/uriid1-experiments/bledom-qt) send. `bledob` comes from
[elk-bledob](https://github.com/8none1/elk-bledob)'s Bluetooth captures of the vendor
app, `melk` from elkbledom's per-model tables.

Writes are capped at 20 per second (10 for `bledob`), about what the controller's chip
handles before it starts dropping frames. Only `bench --fps N` goes past the cap, to
find where your unit gives up.

## Development

```sh
pip install -r requirements-dev.txt
python -m pytest
```

The tests use a fake Bluetooth client, so they run without a strip.
