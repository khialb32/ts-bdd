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
        ["off", "--variant", "legacy"],
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


class RecordingStrip:
    log = []

    def __init__(self, found, variant, **kwargs):
        self.variant = variant

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def power(self, on):
        self.log.append((self.variant.key, "power", on))

    async def color(self, *rgb):
        self.log.append((self.variant.key, "color", rgb))


def test_probe_shows_a_different_color_per_variant_and_stops_on_yes(monkeypatch):
    import asyncio

    from ambilight import cli, device
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
    colors = [(key, rgb) for key, kind, rgb in RecordingStrip.log if kind == "color"]
    assert colors == [("lotus", (255, 0, 0)), ("legacy", (0, 255, 0)), ("legacy", (255, 255, 255))]
