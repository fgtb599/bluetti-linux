"""Bluetti EB3A BLE protocol (Modbus RTU over a GATT characteristic pair).

Register map follows the community bluetti_mqtt project for the EB3A.
"""

from dataclasses import dataclass

WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

# One read of registers 10..49 covers everything the dashboard shows.
POLL_START = 10
POLL_COUNT = 40

EB3A_CAPACITY_WH = 268

# Writable on/off switches (1 = on).
OUTPUT_REGISTERS = {"ac": 3007, "dc": 3008}
WRITE_RESPONSE_LENGTH = 8


class ProtocolError(Exception):
    pass


def crc16(data: bytes) -> int:
    """Modbus CRC-16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def read_command(address: int, count: int) -> bytes:
    """Build a 'read holding registers' (0x03) request."""
    body = bytes([0x01, 0x03]) + address.to_bytes(2, "big") + count.to_bytes(2, "big")
    return body + crc16(body).to_bytes(2, "little")


def write_command(address: int, value: int) -> bytes:
    """Build a 'write single register' (0x06) request."""
    body = bytes([0x01, 0x06]) + address.to_bytes(2, "big") + value.to_bytes(2, "big")
    return body + crc16(body).to_bytes(2, "little")


def check_write_response(raw: bytes, command: bytes) -> None:
    """A successful single-register write is echoed back unchanged."""
    if is_error_response(raw):
        raise ProtocolError(f"device returned error code {raw[2]}")
    if raw != command:
        raise ProtocolError("write was not confirmed")


def response_length(count: int) -> int:
    return 2 * count + 5


def is_error_response(raw: bytes) -> bool:
    return len(raw) >= 5 and bool(raw[1] & 0x80)


def parse_response(raw: bytes, count: int) -> list[int]:
    """Validate a read response and return its register values."""
    if is_error_response(raw):
        raise ProtocolError(f"device returned error code {raw[2]}")
    if len(raw) != response_length(count):
        raise ProtocolError(f"expected {response_length(count)} bytes, got {len(raw)}")
    if crc16(raw[:-2]) != int.from_bytes(raw[-2:], "little"):
        raise ProtocolError("CRC mismatch")
    if raw[0] != 0x01 or raw[1] != 0x03 or raw[2] != 2 * count:
        raise ProtocolError("unexpected response header")
    return [int.from_bytes(raw[3 + 2 * i:5 + 2 * i], "big") for i in range(count)]


@dataclass(frozen=True)
class Status:
    model: str
    serial: int
    arm_version: str
    dsp_version: str
    dc_input_w: int
    ac_input_w: int
    ac_output_w: int
    dc_output_w: int
    generated_kwh: float
    battery_pct: int
    ac_on: bool
    dc_on: bool

    @property
    def input_w(self) -> int:
        return self.dc_input_w + self.ac_input_w

    @property
    def output_w(self) -> int:
        return self.ac_output_w + self.dc_output_w

    @property
    def charging(self) -> bool:
        return self.input_w > self.output_w

    def hours_remaining(self) -> float | None:
        """Rough runtime (discharging) or time to full (charging) estimate."""
        net = self.input_w - self.output_w
        if net == 0:
            return None
        if net > 0:
            wh = (100 - self.battery_pct) / 100 * EB3A_CAPACITY_WH
        else:
            wh = self.battery_pct / 100 * EB3A_CAPACITY_WH
        return wh / abs(net)


def decode_status(regs: list[int]) -> Status:
    def reg(address: int) -> int:
        return regs[address - POLL_START]

    def version(address: int) -> str:
        return f"{(reg(address) + (reg(address + 1) << 16)) / 100:.2f}"

    model = b"".join(reg(a).to_bytes(2, "big") for a in range(10, 16))
    return Status(
        model=model.decode("ascii", "ignore").strip("\x00 "),
        serial=sum(reg(17 + i) << (16 * i) for i in range(4)),
        arm_version=version(23),
        dsp_version=version(25),
        dc_input_w=reg(36),
        ac_input_w=reg(37),
        ac_output_w=reg(38),
        dc_output_w=reg(39),
        generated_kwh=reg(41) / 10,
        battery_pct=reg(43),
        ac_on=reg(48) == 1,
        dc_on=reg(49) == 1,
    )
