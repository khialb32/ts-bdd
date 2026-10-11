import pytest

from ambilight import protocol
from ambilight.protocol import VARIANTS, frame, variant_for_name

APP = VARIANTS["app"]
CLASSIC = VARIANTS["classic"]


def h(packet: bytes) -> str:
    return packet.hex(" ")


def test_frame_wraps_payload_in_head_and_tail():
    assert h(frame(1, 2, 3, 4, 5, 6, 7)) == "7e 01 02 03 04 05 06 07 ef"


def test_frame_rejects_wrong_length():
    with pytest.raises(ValueError):
        frame(1, 2, 3)


# Expected bytes for "classic" are what elkbledom (Home Assistant), elk-led-controller,
# ELK-BLEDOM (Go) and bledom-qt all send to a plain ELK-BLEDOM.
def test_classic_frames():
    assert h(CLASSIC.power(True)) == "7e 00 04 f0 00 01 ff 00 ef"
    assert h(CLASSIC.power(False)) == "7e 00 04 00 00 00 ff 00 ef"
    assert h(CLASSIC.color(1, 2, 3)) == "7e 00 05 03 01 02 03 00 ef"
    assert h(CLASSIC.brightness(50)) == "7e 00 01 32 00 00 00 00 ef"


def test_classic_is_the_default():
    assert protocol.DEFAULT_VARIANT is CLASSIC


# Expected bytes for "app" are the test vectors of the lotus-led library, which
# transcribed them from the Lotus Lantern Android app.
def test_app_power():
    assert h(APP.power(True)) == "7e 04 04 01 00 01 ff 00 ef"
    assert h(APP.power(False)) == "7e 04 04 00 00 00 ff 00 ef"


def test_app_color():
    assert h(APP.color(0xAA, 0xBB, 0xCC)) == "7e 07 05 03 aa bb cc 10 ef"


def test_app_stream_color_uses_streaming_trailer():
    assert h(APP.stream_color(0xAA, 0xBB, 0xCC)) == "7e 07 05 03 aa bb cc 20 ef"


def test_app_brightness_is_a_percentage():
    assert h(APP.brightness(100)) == "7e 04 01 64 ff ff ff 00 ef"
    assert h(APP.brightness(0)) == "7e 04 01 00 ff ff ff 00 ef"


# Expected bytes for bledob and melk are the elkbledom integration's models.json.
def test_bledob_frames():
    bledob = VARIANTS["bledob"]
    assert h(bledob.power(True)) == "7e 07 04 ff 00 01 02 01 ef"
    assert h(bledob.power(False)) == "7e 07 04 00 00 00 02 01 ef"
    assert h(bledob.color(1, 2, 3)) == "7e 07 05 03 01 02 03 0a ef"
    assert h(bledob.brightness(100)) == "7e 04 01 64 01 ff 02 01 ef"
    assert bledob.max_rate == 10


def test_melk_frames_and_login():
    melk = VARIANTS["melk"]
    assert h(melk.power(True)) == "7e 00 04 01 00 00 00 00 ef"
    assert h(melk.power(False)) == "7e 00 04 00 00 00 ff 00 ef"
    assert h(melk.color(1, 2, 3)) == "7e 00 05 03 01 02 03 00 ef"
    assert h(melk.brightness(100)) == "7e 04 01 64 ff 00 ff 00 ef"
    assert [(h(packet), pause) for packet, pause in melk.init] == [("7e 07 83", 1.0), ("7e 04 04", 1.0)]


def test_stream_color_falls_back_to_color_without_a_stream_template():
    assert CLASSIC.stream_color(1, 2, 3) == CLASSIC.color(1, 2, 3)


def test_wake_frames_are_power_on_frames_and_never_melks():
    assert CLASSIC.power_on in protocol.WAKE_FRAMES
    assert APP.power_on in protocol.WAKE_FRAMES
    # Some firmwares read MELK's power-on bytes as "off".
    assert VARIANTS["melk"].power_on not in protocol.WAKE_FRAMES


@pytest.mark.parametrize("variant", VARIANTS.values(), ids=lambda v: v.key)
def test_every_frame_is_nine_bytes(variant):
    for packet in (variant.power(True), variant.power(False), variant.color(1, 2, 3), variant.brightness(42)):
        assert len(packet) == 9
        assert packet[0] == protocol.HEAD and packet[-1] == protocol.TAIL


@pytest.mark.parametrize("rgb", [(-1, 0, 0), (0, 256, 0), (0, 0, 300)])
def test_color_rejects_out_of_range(rgb):
    with pytest.raises(ValueError):
        APP.color(*rgb)


@pytest.mark.parametrize("level", [-1, 101, 255])
def test_brightness_rejects_out_of_range(level):
    with pytest.raises(ValueError):
        APP.brightness(level)


@pytest.mark.parametrize(
    "name", ["ELK-BLEDOM", "ELK-BLEDOM   ", "elk-bledom", "ELK-BLEDOB", "ELK-BULB", "LEDBLE-1234", "MELK-OA10"]
)
def test_known_names_are_recognised(name):
    assert protocol.matches_known_prefix(name)


@pytest.mark.parametrize("name", ["", "JBL Flip 5", "Mi Band"])
def test_other_names_are_not(name):
    assert not protocol.matches_known_prefix(name)


@pytest.mark.parametrize(
    "name, key",
    [
        ("ELK-BLEDOM", "classic"),
        ("ELK-BLEDOM   ", "classic"),
        ("ELK-BLE", "classic"),
        ("ELK-SOMETHING-NEW", "classic"),
        ("ELK-BLEDOB", "bledob"),
        ("ELK-BLEDOM0E", "bledob"),
        ("MELK-OA10", "melk"),
        ("melk-oc10", "melk"),
        ("MODELX", "melk"),
    ],
)
def test_variant_for_name_prefers_longest_prefix(name, key):
    assert variant_for_name(name).key == key


def test_unknown_or_missing_name_falls_back_to_default():
    assert variant_for_name(None) is protocol.DEFAULT_VARIANT
    assert variant_for_name("Something") is protocol.DEFAULT_VARIANT
