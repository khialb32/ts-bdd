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
