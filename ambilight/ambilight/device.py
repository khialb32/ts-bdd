"""Find, connect to and write to an ELK-BLEDOM style LED controller with bleak."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from . import protocol
from .protocol import Variant

# The controllers expose one writable characteristic. Most use fff3 (service fff0),
# some newer ones use ffe1 (service ffe0).
WRITE_CHAR_UUIDS = (
    "0000fff3-0000-1000-8000-00805f9b34fb",
    "0000ffe1-0000-1000-8000-00805f9b34fb",
)
SERVICE_UUIDS = (
    "0000fff0-0000-1000-8000-00805f9b34fb",
    "0000ffe0-0000-1000-8000-00805f9b34fb",
)

# Many of these controllers ship with MAC addresses from this block, and some do not
# advertise a name or their service, so the address is the only hint.
KNOWN_MAC_PREFIXES = ("BE:60:65",)

CONNECT_ATTEMPTS = 3
# A write without response is only queued when write_gatt_char returns; disconnecting
# straight away can drop it, so linger a moment before letting go.
FLUSH_BEFORE_DISCONNECT = 0.6

_ADDRESS = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$|^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$", re.I)


@dataclass
class Found:
    device: BLEDevice | str
    name: str
    rssi: int | None
    service_uuids: list[str]

    @property
    def address(self) -> str:
        return self.device if isinstance(self.device, str) else self.device.address

    @property
    def is_candidate(self) -> bool:
        return is_candidate(self.name, self.service_uuids, self.address)


def is_candidate(name: str | None, service_uuids: list[str] | None = None, address: str = "") -> bool:
    """True if the advertisement looks like a LotusLanternX-compatible controller."""
    if name and protocol.matches_known_prefix(name):
        return True
    if address.upper().startswith(KNOWN_MAC_PREFIXES):
        return True
    uuids = {u.lower() for u in (service_uuids or [])}
    return any(u in uuids for u in SERVICE_UUIDS)


async def scan(timeout: float = 8.0) -> list[Found]:
    """Scan for BLE devices, strongest signal first."""
    seen = await BleakScanner.discover(timeout=timeout, return_adv=True)
    found = [
        Found(
            device=dev,
            name=adv.local_name or dev.name or "",
            rssi=adv.rssi,
            service_uuids=list(adv.service_uuids),
        )
        for dev, adv in seen.values()
    ]
    found.sort(key=lambda f: f.rssi, reverse=True)
    return found


async def resolve(identifier: str | None, timeout: float = 8.0) -> Found:
    """Turn an address, a name, or nothing (auto-pick) into a discovered device.

    An address is a MAC on Windows/Linux and a UUID on macOS. A name matches
    case-insensitively, and a prefix is enough ("ELK" finds "ELK-BLEDOM").
    """
    found = await scan(timeout)
    if identifier:
        wanted = identifier.lower()
        for f in found:
            if f.address.lower() == wanted:
                return f
        for f in found:
            if f.name.lower().startswith(wanted):
                return f
        if _ADDRESS.match(identifier):
            # Controllers often skip advertising for a while after a disconnect, but
            # still accept a connection to their address.
            print(f"{identifier} did not show up in the scan; trying to connect anyway.")
            return Found(device=identifier, name="", rssi=None, service_uuids=[])
        raise LookupError(
            f"No device matching {identifier!r} was found. Is the strip powered, "
            "and is the phone app closed? Run 'scan' to see what is visible."
        )
    candidates = [f for f in found if f.is_candidate]
    if not candidates:
        raise LookupError(
            "No LED controller found. Close LotusLanternX on your phone (the strip "
            "accepts one connection at a time), then run 'scan --all'."
        )
    if len(candidates) > 1:
        listed = ", ".join(f"{c.name} [{c.address}]" for c in candidates)
        print(f"Several controllers found ({listed}); using the strongest signal.")
    return candidates[0]


def pick_write_char(client: BleakClient) -> BleakGATTCharacteristic:
    """Find the controller's command characteristic among the discovered services."""
    for uuid in WRITE_CHAR_UUIDS:
        char = client.services.get_characteristic(uuid)
        if char is not None:
            return char
    # Unknown firmware: fall back to the first writable characteristic outside
    # the standard GAP/GATT services.
    for service in client.services:
        if service.uuid.startswith(("00001800", "00001801")):
            continue
        for char in service.characteristics:
            if {"write", "write-without-response"} & set(char.properties):
                return char
    raise LookupError("The device has no writable characteristic; it is probably not an LED controller.")


class LedStrip:
    """An open connection to one strip. Use as ``async with LedStrip(found) as strip``."""

    def __init__(
        self,
        found: Found,
        variant: Variant | None = None,
        *,
        with_response: bool | None = None,
        max_rate: float | None = None,
    ):
        self.found = found
        self.variant = variant or protocol.variant_for_name(found.name)
        self._with_response = with_response
        self._min_interval = 1 / (max_rate or self.variant.max_rate)
        self._last_write = 0.0
        self._client = BleakClient(found.device, timeout=20)
        self._char: BleakGATTCharacteristic | None = None

    async def __aenter__(self) -> LedStrip:
        # Right after another client lets go, the controller often refuses the first
        # connection, so give it a couple of retries.
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                await self._client.connect()
                break
            except (BleakError, asyncio.TimeoutError):
                if attempt == CONNECT_ATTEMPTS:
                    raise
                await asyncio.sleep(1)
        self._char = pick_write_char(self._client)
        if self._with_response is None:
            # Write-without-response is much faster, which matters for screen sync.
            self._with_response = "write-without-response" not in self._char.properties
        for packet, pause in self.variant.init:
            await self._client.write_gatt_char(self.char, packet, response=self.with_response)
            await asyncio.sleep(pause)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._last_write and not self.with_response:
            await asyncio.sleep(FLUSH_BEFORE_DISCONNECT)
        await self._client.disconnect()

    @property
    def char(self) -> BleakGATTCharacteristic:
        assert self._char is not None, "not connected"
        return self._char

    @property
    def with_response(self) -> bool:
        return bool(self._with_response)

    @property
    def services(self):
        return self._client.services

    async def firmware_id(self) -> str:
        """The command characteristic reads back a fixed ID such as ELKP10Y60H_OLSMN_V02."""
        if "read" not in self.char.properties:
            return "unknown"
        try:
            data = await self._client.read_gatt_char(self.char)
        except BleakError:
            return "unknown"
        return data.decode("ascii", errors="replace").replace("\x00", "").strip() or "unknown"

    async def write(self, packet: bytes) -> None:
        wait = self._last_write + self._min_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        await self._client.write_gatt_char(self.char, packet, response=self.with_response)
        self._last_write = time.monotonic()

    async def power(self, on: bool) -> None:
        await self.write(self.variant.power(on))

    async def color(self, r: int, g: int, b: int) -> None:
        await self.write(self.variant.color(r, g, b))

    async def stream_color(self, r: int, g: int, b: int) -> None:
        """Color for continuous updates (screen sync): the firmware skips its fade logic."""
        await self.write(self.variant.stream_color(r, g, b))

    async def brightness(self, percent: int) -> None:
        await self.write(self.variant.brightness(percent))
