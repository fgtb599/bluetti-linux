import unittest

from bluetti.protocol import (
    OUTPUT_REGISTERS,
    POLL_COUNT,
    POLL_START,
    ProtocolError,
    check_write_response,
    crc16,
    decode_status,
    parse_response,
    read_command,
    write_command,
)


def make_response(regs):
    body = bytes([0x01, 0x03, 2 * len(regs)]) + b"".join(r.to_bytes(2, "big") for r in regs)
    return body + crc16(body).to_bytes(2, "little")


class ProtocolTest(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(read_command(0, 1), bytes.fromhex("010300000001840a"))

    def test_poll_command(self):
        cmd = read_command(POLL_START, POLL_COUNT)
        self.assertEqual(cmd[:6], bytes.fromhex("0103000a0028"))

    def test_decode_status(self):
        regs = [0] * POLL_COUNT

        def put(addr, value):
            regs[addr - POLL_START] = value

        for i, word in enumerate([0x4542, 0x3341, 0, 0, 0, 0]):  # "EB3A"
            put(10 + i, word)
        put(17, 0x5678)
        put(18, 0x1234)
        put(23, 8700)  # firmware words seen on a real EB3A
        put(24, 3)
        put(36, 120)
        put(37, 0)
        put(38, 45)
        put(39, 10)
        put(41, 123)
        put(43, 87)
        put(48, 1)

        s = decode_status(parse_response(make_response(regs), POLL_COUNT))
        self.assertEqual(s.model, "EB3A")
        self.assertEqual(s.serial, 0x12345678)
        self.assertEqual(s.arm_version, "2053.08")
        self.assertEqual((s.input_w, s.output_w, s.battery_pct), (120, 55, 87))
        self.assertAlmostEqual(s.generated_kwh, 12.3)
        self.assertTrue(s.ac_on)
        self.assertFalse(s.dc_on)
        self.assertTrue(s.charging)

    def test_bad_crc_rejected(self):
        raw = bytearray(make_response([0] * POLL_COUNT))
        raw[-1] ^= 0xFF
        with self.assertRaises(ProtocolError):
            parse_response(bytes(raw), POLL_COUNT)

    def test_write_command(self):
        cmd = write_command(OUTPUT_REGISTERS["dc"], 1)
        self.assertEqual(cmd[:6], bytes.fromhex("01060bc00001"))
        self.assertEqual(crc16(cmd[:-2]), int.from_bytes(cmd[-2:], "little"))

    def test_write_echo_accepted(self):
        cmd = write_command(OUTPUT_REGISTERS["ac"], 0)
        check_write_response(cmd, cmd)

    def test_write_mismatch_rejected(self):
        with self.assertRaises(ProtocolError):
            check_write_response(write_command(3007, 1), write_command(3007, 0))

    def test_error_response_rejected(self):
        body = bytes([0x01, 0x83, 0x02])
        with self.assertRaises(ProtocolError):
            parse_response(body + crc16(body).to_bytes(2, "little"), POLL_COUNT)


if __name__ == "__main__":
    unittest.main()
