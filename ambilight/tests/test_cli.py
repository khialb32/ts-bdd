import pytest

from ambilight.cli import build_parser, parse_color


@pytest.mark.parametrize(
    "parts, rgb",
    [
        (["red"], (255, 0, 0)),
        (["RED"], (255, 0, 0)),
        (["ff8000"], (255, 128, 0)),
        (["#00ff00"], (0, 255, 0)),
        (["1", "2", "3"], (1, 2, 3)),
    ],
)
def test_parse_color(parts, rgb):
    assert parse_color(parts) == rgb


@pytest.mark.parametrize("parts", [["nope"], ["12345"], ["1", "2"], ["0", "0", "256"], ["zzzzzz"]])
def test_parse_color_rejects(parts):
    with pytest.raises(ValueError):
        parse_color(parts)


def test_every_command_parses():
    parser = build_parser()
    for argv in (
        ["scan", "--all"],
        ["inspect", "-d", "ELK"],
        ["on"],
        ["off", "--variant", "classic"],
        ["color", "255", "0", "0"],
        ["brightness", "50"],
        ["test", "--no-with-response"],
        ["bench", "--fps", "15", "--seconds", "3"],
        ["probe"],
    ):
        assert callable(parser.parse_args(argv).func)


def test_brightness_out_of_range_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["brightness", "150"])


@pytest.mark.parametrize("fps", ["0", "-5", "nan", "inf", "1000"])
def test_bench_rejects_nonsense_fps(fps):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["bench", "--fps", fps])


def test_bench_fps_defaults_to_the_variant_cap():
    assert build_parser().parse_args(["bench"]).fps is None


@pytest.mark.parametrize(
    "error, message",
    [
        (TimeoutError(), "did not answer in time"),
        (FileNotFoundError(2, "No such file"), "cannot reach the Bluetooth service"),
        (OSError("radio off"), "bluetooth error"),
        (EOFError(), "needs an answer"),
    ],
)
def test_main_turns_common_failures_into_hints(monkeypatch, capsys, error, message):
    from ambilight import cli

    async def failing(args):
        raise error

    monkeypatch.setattr(cli, "cmd_scan", failing)
    assert cli.main(["scan"]) == 1
    assert message in capsys.readouterr().err


class RecordingStrip:
    log = []

    def __init__(self, found, variant, **kwargs):
        self.variant = variant

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def write(self, packet):
        self.log.append((self.variant.key, "write", packet))

    async def power(self, on):
        self.log.append((self.variant.key, "power", on))

    async def color(self, *rgb):
        self.log.append((self.variant.key, "color", rgb))


def test_probe_wakes_the_strip_tries_variants_in_order_and_stops_on_yes(monkeypatch):
    import asyncio

    from ambilight import cli, device, protocol
    from ambilight.device import Found

    async def fake_resolve(identifier, timeout):
        return Found(device="BE:60:65:00:00:01", name="ELK-BLEDOM", rssi=-50, service_uuids=[])

    answers = iter(["n", "y"])
    monkeypatch.setattr(device, "resolve", fake_resolve)
    monkeypatch.setattr(cli, "LedStrip", RecordingStrip)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    RecordingStrip.log = []

    args = build_parser().parse_args(["probe"])
    assert asyncio.run(cli.cmd_probe(args)) == 0
    log = RecordingStrip.log
    assert [key for key, kind, _ in log if kind == "power"] == ["app", "classic"]
    for key in ("app", "classic"):
        assert [p for k, kind, p in log if k == key and kind == "write"] == list(protocol.WAKE_FRAMES)
    assert log[-1] == ("classic", "color", (255, 255, 255))


def test_probe_moves_on_when_a_variant_drops_the_connection(monkeypatch):
    import asyncio

    from bleak.exc import BleakError

    from ambilight import cli, device
    from ambilight.device import Found

    class HangsUpUnlessMelk(RecordingStrip):
        async def write(self, packet):
            if self.variant.key != "melk":
                raise BleakError("Not connected")
            await super().write(packet)

    async def fake_resolve(identifier, timeout):
        return Found(device="BE:60:65:00:00:01", name="", rssi=None, service_uuids=[])

    monkeypatch.setattr(device, "resolve", fake_resolve)
    monkeypatch.setattr(cli, "LedStrip", HangsUpUnlessMelk)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    RecordingStrip.log = []

    assert asyncio.run(cli.cmd_probe(build_parser().parse_args(["probe"]))) == 0
    assert RecordingStrip.log[-1] == ("melk", "color", (255, 255, 255))


def test_probe_tries_the_forced_variant_first(monkeypatch):
    import asyncio

    from ambilight import cli, device
    from ambilight.device import Found

    async def fake_resolve(identifier, timeout):
        return Found(device="BE:60:65:00:00:01", name="ELK-BLEDOM", rssi=-50, service_uuids=[])

    monkeypatch.setattr(device, "resolve", fake_resolve)
    monkeypatch.setattr(cli, "LedStrip", RecordingStrip)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    RecordingStrip.log = []

    assert asyncio.run(cli.cmd_probe(build_parser().parse_args(["probe", "--variant", "bledob"]))) == 0
    assert RecordingStrip.log[0][0] == "bledob"
