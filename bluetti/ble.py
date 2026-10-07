"""Background BLE poller: finds the EB3A, connects, reads status in a loop and applies switch commands."""

import asyncio
import logging

from bleak import BleakClient, BleakScanner

from .protocol import (
    NOTIFY_UUID,
    OUTPUT_REGISTERS,
    POLL_COUNT,
    POLL_START,
    WRITE_RESPONSE_LENGTH,
    WRITE_UUID,
    ProtocolError,
    check_write_response,
    decode_status,
    is_error_response,
    parse_response,
    read_command,
    response_length,
    write_command,
)

log = logging.getLogger(__name__)


def is_eb3a(name):
    return (name or "").startswith("EB3A")


class Poller:
    """Runs in its own asyncio thread; the public methods are safe to call from the GTK thread."""

    def __init__(self, on_status, on_state, on_device, address=None, interval=5.0):
        self.on_status = on_status
        self.on_state = on_state
        self.on_device = on_device
        self.address = address
        self.interval = interval
        self.loop = None
        self.commands = None
        self.session = None
        self.buffer = bytearray()
        self.expected = 0
        self.waiter = None

    def set_output(self, port, on):
        """Queue an AC/DC on/off command."""
        if self.loop:
            command = write_command(OUTPUT_REGISTERS[port], int(on))
            self.loop.call_soon_threadsafe(self.commands.put_nowait, command)

    def set_address(self, address):
        """Switch to another unit (None = first EB3A found); drops the current connection."""

        def apply():
            self.address = address
            if self.session:
                self.session.cancel()

        if self.loop:
            self.loop.call_soon_threadsafe(apply)

    def scan(self, on_result, timeout=8.0):
        """Look for nearby EB3A units; on_result gets [(name, address)] in the BLE thread."""

        async def discover():
            try:
                devices = await BleakScanner.discover(timeout=timeout)
            except Exception as e:
                log.warning("scan failed: %s", e)
                devices = []
            on_result(sorted({(d.name, d.address) for d in devices if is_eb3a(d.name)}))

        if self.loop:
            asyncio.run_coroutine_threadsafe(discover(), self.loop)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.commands = asyncio.Queue()
        while True:
            self.session = asyncio.create_task(self._session())
            try:
                await self.session
            except asyncio.CancelledError:
                pass  # set_address() asked for another device; start over right away

    async def _session(self):
        try:
            self.on_state("Searching…")
            device = await self._find()
            if device is None:
                self.on_state("EB3A not found")
                await asyncio.sleep(10)
                return
            self.on_state("Connecting…")
            async with BleakClient(device) as client:
                self.on_device(device.name or "EB3A", device.address)
                await self._poll(client)
        except Exception as e:
            log.warning("connection lost: %s", e)
        self.on_state("Disconnected")
        await asyncio.sleep(5)

    async def _find(self):
        if self.address:
            return await BleakScanner.find_device_by_address(self.address, timeout=15)
        return await BleakScanner.find_device_by_filter(lambda d, _ad: is_eb3a(d.name), timeout=15)

    # A response arrives split across several notifications.
    def _on_notify(self, _char, data):
        self.buffer.extend(data)
        done = len(self.buffer) >= self.expected or is_error_response(self.buffer)
        if self.waiter and not self.waiter.done() and done:
            self.waiter.set_result(bytes(self.buffer))

    async def _request(self, client, command, expected):
        self.buffer.clear()
        self.expected = expected
        self.waiter = self.loop.create_future()
        await client.write_gatt_char(WRITE_UUID, command)
        return await asyncio.wait_for(self.waiter, timeout=5)

    async def _poll(self, client):
        await client.start_notify(NOTIFY_UUID, self._on_notify)
        self.on_state("Connected")
        # Drop switch presses made while disconnected rather than replaying them later.
        while not self.commands.empty():
            self.commands.get_nowait()

        read = read_command(POLL_START, POLL_COUNT)
        while client.is_connected:
            raw = await self._request(client, read, response_length(POLL_COUNT))
            status = decode_status(parse_response(raw, POLL_COUNT))
            log.debug("status: %s", status)
            self.on_status(status)
            try:
                command = await asyncio.wait_for(self.commands.get(), timeout=self.interval)
            except TimeoutError:
                continue
            log.info("write %s", command.hex())
            try:
                check_write_response(await self._request(client, command, WRITE_RESPONSE_LENGTH), command)
            except ProtocolError as e:
                # The next poll puts the switch back to the device's real state.
                log.warning("switch command failed: %s", e)
