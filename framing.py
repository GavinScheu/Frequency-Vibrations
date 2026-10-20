"""Frame layout: length (2 bytes, big-endian) + CRC-16 of the length (2 bytes) + body (Jacob).

The preamble and sync byte are added by modem.modulate, not here.
"""

import binascii
import struct

from common import CRC_INIT, FramingError, HEADER_BYTES, LENGTH_BYTES, MAX_BODY, MIN_BODY


def _crc(length_field: bytes) -> int:
    return binascii.crc_hqx(length_field, CRC_INIT)


def frame(body: bytes) -> bytes:
    """Return header + body. Raises ValueError unless MIN_BODY <= len(body) <= MAX_BODY."""
    if not MIN_BODY <= len(body) <= MAX_BODY:
        raise ValueError(f"body is {len(body)} bytes; must be {MIN_BODY}..{MAX_BODY}")
    header = struct.pack(">H", len(body))
    return header + struct.pack(">H", _crc(header)) + body


def parse_header(header: bytes) -> int:
    """Validate the 4-byte header and return the body length.

    Shared with the demodulator, which needs the length to know how many more
    bits to decode. Raises FramingError on a short header, bad CRC, or a
    length outside MIN_BODY..MAX_BODY.
    """
    if len(header) < HEADER_BYTES:
        raise FramingError(f"header is {len(header)} bytes; need {HEADER_BYTES}")
    length, crc = struct.unpack(">HH", header[:HEADER_BYTES])
    if crc != _crc(header[:LENGTH_BYTES]):
        raise FramingError("bad header CRC")
    if not MIN_BODY <= length <= MAX_BODY:
        raise FramingError(f"length {length} outside {MIN_BODY}..{MAX_BODY}")
    return length


def deframe(data: bytes) -> bytes:
    """Check the header and return exactly `length` bytes of body.

    Bytes after the body are ignored. Raises FramingError on a bad header
    or fewer than `length` body bytes.
    """
    length = parse_header(data)
    end = HEADER_BYTES + length
    if len(data) < end:
        raise FramingError(f"frame truncated: have {len(data) - HEADER_BYTES} of {length} body bytes")
    return data[HEADER_BYTES:end]
