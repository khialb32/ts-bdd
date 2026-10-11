import asyncio
import time
from types import SimpleNamespace

import pytest

from ambilight import device
from ambilight.device import Found, LedStrip


class FakeChar(SimpleNamespace):
    pass


class FakeServices:
    def __init__(self, services):
        self._services = services

    def __iter__(self):
        return iter(self._services)

    def get_characteristic(self, uuid):
        for service in self._services:
            for char in service.characteristics:
                if char.uuid == uuid:
                    return char
        return None


def service(uuid, *chars):
    return SimpleNamespace(uuid=uuid, description="", characteristics=list(chars))


def char(uuid, *properties, handle=1):
    return FakeChar(uuid=uuid, properties=list(properties), handle=handle)


FFF3 = "0000fff3-0000-1000-8000-00805f9b34fb"
FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"


class FakeClient:
    def __init__(self, services):
        self.services = FakeServices(services)
        self.writes = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def write_gatt_char(self, char, data, response):
        self.writes.append((char.uuid, bytes(data), response))


def found(name="ELK-BLEDOM", rssi=-60, uuids=(), address="AA:BB:CC:00:00:01"):
    return Found(device=SimpleNamespace(address=address, name=name), name=name, rssi=rssi, service_uuids=list(uuids))


def strip_with(client, monkeypatch, name="ELK-BLEDOM", **kwargs):
    monkeypatch.setattr(device, "BleakClient", lambda *a, **k: client)
    return LedStrip(found(name), **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_pick_prefers_fff3():
    client = FakeClient([service("0000fff0", char(FFE1, "write", handle=5), char(FFF3, "write", handle=9))])
    assert device.pick_write_char(client).uuid == FFF3


def test_pick_falls_back_to_ffe1():
    client = FakeClient([service("0000ffe0", char(FFE1, "write-without-response"))])
    assert device.pick_write_char(client).uuid == FFE1


def test_pick_falls_back_to_any_writable_vendor_char():
    gap = service("00001800-0000-1000-8000-00805f9b34fb", char("00002a00", "read", "write"))
    vendor = service("0000abcd", char("0000abce", "notify"), char("0000abcf", "write"))
    assert device.pick_write_char(FakeClient([gap, vendor])).uuid == "0000abcf"


def test_pick_raises_without_writable_char():
    with pytest.raises(LookupError):
        device.pick_write_char(FakeClient([service("0000abcd", char("0000abce", "read"))]))


def test_writes_without_response_when_supported(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write", "write-without-response"))])

    async def go():
        async with strip_with(client, monkeypatch) as strip:
            await strip.color(255, 0, 0)

    run(go())
    assert client.writes == [(FFF3, bytes.fromhex("7e 07 05 03 ff 00 00 10 ef"), False)]
    assert not client.connected


def test_writes_with_response_when_that_is_all_it_supports(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write"))])

    async def go():
        async with strip_with(client, monkeypatch) as strip:
            await strip.power(True)

    run(go())
    assert client.writes[0][2] is True


def test_with_response_can_be_forced(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write", "write-without-response"))])

    async def go():
        async with strip_with(client, monkeypatch, with_response=True) as strip:
            await strip.power(False)

    run(go())
    assert client.writes[0][2] is True


def test_writes_are_rate_limited(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write-without-response"))])
    times = []
    original = client.write_gatt_char

    async def timed(*a, **k):
        times.append(asyncio.get_running_loop().time())
        await original(*a, **k)

    client.write_gatt_char = timed

    async def go():
        async with strip_with(client, monkeypatch, max_rate=50) as strip:
            for _ in range(4):
                await strip.stream_color(1, 2, 3)

    run(go())
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap >= 0.018 for gap in gaps), gaps


def test_is_candidate_by_name_or_service():
    assert device.is_candidate("ELK-BLEDOM")
    assert device.is_candidate("", ["0000FFF0-0000-1000-8000-00805F9B34FB"])
    assert not device.is_candidate("Headphones", ["0000180f-0000-1000-8000-00805f9b34fb"])


def test_resolve_picks_strongest_candidate(monkeypatch):
    devices = [found("Headphones", -40, address="A"), found("ELK-BLEDOM", -80, address="B"), found("ELK-BLEDOM", -50, address="C")]

    async def fake_scan(timeout):
        return sorted(devices, key=lambda f: f.rssi, reverse=True)

    monkeypatch.setattr(device, "scan", fake_scan)
    assert run(device.resolve(None)).address == "C"
    assert run(device.resolve("b")).address == "B"
    assert run(device.resolve("head")).address == "A"
    with pytest.raises(LookupError):
        run(device.resolve("nothing-like-this"))


def test_resolve_explains_when_nothing_is_found(monkeypatch):
    async def fake_scan(timeout):
        return [found("Headphones", -40)]

    monkeypatch.setattr(device, "scan", fake_scan)
    with pytest.raises(LookupError, match="LotusLanternX"):
        run(device.resolve(None))


def test_rate_limit_defaults_to_the_variant(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write-without-response"))])
    assert strip_with(client, monkeypatch)._min_interval == pytest.approx(1 / 20)
    assert strip_with(client, monkeypatch, name="ELK-BLEDOB")._min_interval == pytest.approx(1 / 10)
    assert strip_with(client, monkeypatch, max_rate=40)._min_interval == pytest.approx(1 / 40)


def test_melk_gets_its_login_before_any_command(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write-without-response"))])
    monkeypatch.setattr(device.asyncio, "sleep", _no_sleep)

    async def go():
        async with strip_with(client, monkeypatch, name="MELK-OA10") as strip:
            await strip.power(True)

    run(go())
    assert [data.hex(" ") for _, data, _ in client.writes] == ["7e 07 83", "7e 04 04", "7e 00 04 01 00 00 00 00 ef"]


def test_connect_is_retried(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write-without-response"))])
    failures = [device.BleakError("busy"), asyncio.TimeoutError()]
    original = client.connect

    async def flaky_connect():
        if failures:
            raise failures.pop(0)
        await original()

    client.connect = flaky_connect
    monkeypatch.setattr(device.asyncio, "sleep", _no_sleep)

    async def go():
        async with strip_with(client, monkeypatch):
            assert client.connected

    run(go())


def test_connect_gives_up_after_three_attempts(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write-without-response"))])
    calls = []

    async def failing_connect():
        calls.append(1)
        raise device.BleakError("busy")

    client.connect = failing_connect
    monkeypatch.setattr(device.asyncio, "sleep", _no_sleep)

    async def go():
        async with strip_with(client, monkeypatch):
            pass

    with pytest.raises(device.BleakError):
        run(go())
    assert len(calls) == device.CONNECT_ATTEMPTS


def test_firmware_id_is_read_from_the_command_characteristic(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "read", "write-without-response"))])

    async def read(char):
        return b"ELKP10Y60H_OLSMN_V02\x00 "

    client.read_gatt_char = read

    async def go():
        async with strip_with(client, monkeypatch) as strip:
            return await strip.firmware_id()

    assert run(go()) == "ELKP10Y60H_OLSMN_V02"


async def _no_sleep(_seconds):
    return None


def test_lingers_before_disconnecting_after_unacknowledged_writes(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write-without-response"))])
    monkeypatch.setattr(device, "FLUSH_BEFORE_DISCONNECT", 0.6)
    sleeps = []

    async def record(seconds):
        sleeps.append((seconds, client.connected))

    monkeypatch.setattr(device.asyncio, "sleep", record)

    async def go():
        async with strip_with(client, monkeypatch) as strip:
            await strip.power(True)

    run(go())
    assert (0.6, True) in sleeps
    assert not client.connected


def test_unknown_mac_prefix_counts_as_candidate():
    assert device.is_candidate("", [], "be:60:65:aa:bb:cc")
    assert not device.is_candidate("", [], "11:22:33:44:55:66")


@pytest.mark.parametrize(
    "address, expected",
    [
        ("BE:60:65:12:34:56", "BE:60:65:12:34:56"),
        ("be-60-65-12-34-56", "BE:60:65:12:34:56"),
        ("2F4C9A1E-8B3D-4E5F-9A0B-1C2D3E4F5A6B", "2F4C9A1E-8B3D-4E5F-9A0B-1C2D3E4F5A6B"),
    ],
)
def test_resolve_connects_to_an_unseen_address_anyway(monkeypatch, address, expected):
    async def fake_scan(timeout):
        return []

    monkeypatch.setattr(device, "scan", fake_scan)
    target = run(device.resolve(address))
    assert target.address == expected and target.rssi is None


def test_resolve_matches_a_dashed_mac_against_the_scan(monkeypatch):
    async def fake_scan(timeout):
        return [found("ELK-BLEDOM", -50, address="BE:60:65:12:34:56")]

    monkeypatch.setattr(device, "scan", fake_scan)
    assert run(device.resolve("be-60-65-12-34-56")).name == "ELK-BLEDOM"


def test_resolve_prefers_a_name_match_over_a_stronger_service_only_match(monkeypatch, capsys):
    fff0 = "0000fff0-0000-1000-8000-00805f9b34fb"
    devices = [found("", -30, uuids=[fff0], address="AA:00:00:00:00:01"), found("ELK-BLEDOM", -70, address="B")]

    async def fake_scan(timeout):
        return devices

    monkeypatch.setattr(device, "scan", fake_scan)
    assert run(device.resolve(None)).address == "B"


def test_resolve_warns_when_only_a_service_uuid_matched(monkeypatch, capsys):
    async def fake_scan(timeout):
        return [found("", -30, uuids=["0000ffe0-0000-1000-8000-00805f9b34fb"], address="AA:00:00:00:00:01")]

    monkeypatch.setattr(device, "scan", fake_scan)
    run(device.resolve(None))
    assert "another gadget" in capsys.readouterr().out


def test_pick_skips_a_known_uuid_that_is_not_writable():
    client = FakeClient([service("0000fff0", char(FFF3, "read", "notify"), char("0000fff9", "write"))])
    assert device.pick_write_char(client).uuid == "0000fff9"


def test_disconnects_when_setup_fails_after_connecting(monkeypatch):
    client = FakeClient([service("0000abcd", char("0000abce", "read"))])

    async def go():
        async with strip_with(client, monkeypatch):
            pass

    with pytest.raises(LookupError):
        run(go())
    assert not client.connected


def test_disconnects_even_if_the_flush_wait_is_interrupted(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write-without-response"))])
    monkeypatch.setattr(device, "FLUSH_BEFORE_DISCONNECT", 0.6)

    async def interrupted(seconds):
        raise asyncio.CancelledError

    async def go():
        async with strip_with(client, monkeypatch) as strip:
            await strip.power(True)
            monkeypatch.setattr(device.asyncio, "sleep", interrupted)

    with pytest.raises(asyncio.CancelledError):
        run(go())
    assert not client.connected


def test_slow_writes_do_not_lower_the_rate(monkeypatch):
    client = FakeClient([service("0000fff0", char(FFF3, "write"))])
    starts = []

    async def slow_write(char, data, response):
        starts.append(time.monotonic())
        await asyncio.sleep(0.015)

    client.write_gatt_char = slow_write

    async def go():
        async with strip_with(client, monkeypatch, max_rate=40) as strip:
            for _ in range(6):
                await strip.stream_color(1, 2, 3)

    run(go())
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    # 25 ms apart (the cap), not 25 + 15 ms.
    assert all(0.022 <= gap <= 0.035 for gap in gaps), gaps

