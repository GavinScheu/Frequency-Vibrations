import binascii
import os
import struct

import pytest

from common import CRC_INIT, FramingError, HEADER_BYTES, MAX_BODY, MIN_BODY
from framing import deframe, frame, parse_header


def raw_header(length: int) -> bytes:
    """A header with a valid CRC for any length, bypassing frame()'s checks."""
    h = struct.pack(">H", length)
    return h + struct.pack(">H", binascii.crc_hqx(h, CRC_INIT))


def test_crc_variant_is_ccitt_false():
    # Standard check value for CRC-16/CCITT-FALSE; any reimplementation must match
    assert binascii.crc_hqx(b"123456789", CRC_INIT) == 0x29B1


@pytest.mark.parametrize("body", [os.urandom(MIN_BODY), os.urandom(100), os.urandom(MAX_BODY)])
def test_round_trip(body):
    assert deframe(frame(body)) == body


def test_layout():
    body = os.urandom(MIN_BODY)
    f = frame(body)
    header = struct.pack(">H", MIN_BODY)
    assert f == header + struct.pack(">H", binascii.crc_hqx(header, CRC_INIT)) + body


@pytest.mark.parametrize("n", [0, 1, MIN_BODY - 1, MAX_BODY + 1])
def test_frame_rejects_bad_size(n):
    with pytest.raises(ValueError):
        frame(b"x" * n)


def test_trailing_bytes_ignored():
    # demodulate may hand over extra samples' worth of bytes; only `length` are body
    body = os.urandom(MIN_BODY)
    assert deframe(frame(body) + b"junk") == body


@pytest.mark.parametrize("bit", range(HEADER_BYTES * 8))
def test_corrupted_header_rejected(bit):
    f = bytearray(frame(os.urandom(MIN_BODY)))
    f[bit // 8] ^= 1 << (bit % 8)
    with pytest.raises(FramingError):
        deframe(bytes(f))


def test_all_zero_header_rejected():
    # Silence after the sync byte demodulates as zeros
    with pytest.raises(FramingError, match="CRC"):
        parse_header(b"\x00" * HEADER_BYTES)


@pytest.mark.parametrize("length", list(range(MIN_BODY)) + [MAX_BODY + 1, 0xFFFF])
def test_length_out_of_range_rejected_even_with_valid_crc(length):
    with pytest.raises(FramingError, match="outside"):
        parse_header(raw_header(length))


@pytest.mark.parametrize("length", [MIN_BODY, MAX_BODY])
def test_length_limits_accepted(length):
    assert parse_header(raw_header(length)) == length


@pytest.mark.parametrize("n", [0, 1, HEADER_BYTES - 1])
def test_short_header_rejected(n):
    with pytest.raises(FramingError):
        deframe(frame(os.urandom(MIN_BODY))[:n])


def test_truncated_body_rejected():
    with pytest.raises(FramingError, match="truncated"):
        deframe(frame(os.urandom(MIN_BODY))[:-1])


def test_parse_header_returns_length():
    f = frame(os.urandom(40))
    assert parse_header(f) == 40
    assert parse_header(f[:HEADER_BYTES]) == 40


@pytest.mark.parametrize("bit", range(HEADER_BYTES * 8))
def test_parse_header_rejects_corruption(bit):
    h = bytearray(frame(os.urandom(MIN_BODY))[:HEADER_BYTES])
    h[bit // 8] ^= 1 << (bit % 8)
    with pytest.raises(FramingError):
        parse_header(bytes(h))
