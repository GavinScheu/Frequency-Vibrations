import binascii
import os
import struct

import pytest

from common import FramingError, HEADER_BYTES, MAX_BODY
from framing import deframe, frame, parse_header


@pytest.mark.parametrize("body", [b"", b"\x00", os.urandom(100), os.urandom(MAX_BODY)])
def test_round_trip(body):
    assert deframe(frame(body)) == body


def test_layout():
    body = b"abc"
    f = frame(body)
    header = struct.pack(">H", 3)
    assert f == header + struct.pack(">H", binascii.crc_hqx(header, 0)) + body


def test_oversized_body_rejected_on_send():
    with pytest.raises(ValueError):
        frame(b"x" * (MAX_BODY + 1))


def test_trailing_bytes_ignored():
    # demodulate may hand over extra samples' worth of bytes; only `length` are body
    assert deframe(frame(b"abc") + b"junk") == b"abc"


@pytest.mark.parametrize("bit", range(HEADER_BYTES * 8))
def test_corrupted_header_rejected(bit):
    f = bytearray(frame(b"hello"))
    f[bit // 8] ^= 1 << (bit % 8)
    with pytest.raises(FramingError):
        deframe(bytes(f))


def test_length_over_cap_rejected_even_with_valid_crc():
    header = struct.pack(">H", MAX_BODY + 1)
    data = header + struct.pack(">H", binascii.crc_hqx(header, 0)) + b"x" * (MAX_BODY + 1)
    with pytest.raises(FramingError):
        deframe(data)


@pytest.mark.parametrize("n", [0, 1, HEADER_BYTES - 1])
def test_short_header_rejected(n):
    with pytest.raises(FramingError):
        deframe(frame(b"hello")[:n])


def test_truncated_body_rejected():
    with pytest.raises(FramingError):
        deframe(frame(b"hello")[:-1])


def test_parse_header_returns_length():
    assert parse_header(frame(b"hello")) == 5
    assert parse_header(frame(b"hello")[:HEADER_BYTES]) == 5


@pytest.mark.parametrize("bit", range(HEADER_BYTES * 8))
def test_parse_header_rejects_corruption(bit):
    h = bytearray(frame(b"hello")[:HEADER_BYTES])
    h[bit // 8] ^= 1 << (bit % 8)
    with pytest.raises(FramingError):
        parse_header(bytes(h))
