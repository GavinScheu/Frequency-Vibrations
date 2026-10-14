"""Frame layout: length (2 bytes, big-endian) + CRC-16 of the length (2 bytes) + body (Jacob).

The preamble and sync byte are added by modem.modulate, not here.
"""

import binascii
import struct

from common import CRC_BYTES, FramingError, HEADER_BYTES, LENGTH_BYTES, MAX_BODY


def frame(body: bytes) -> bytes:
    """Return header + body. Raises ValueError if body is longer than MAX_BODY."""
    # TODO:
    #   - reject len(body) > MAX_BODY
    #   - header = struct.pack(">H", len(body))
    #   - crc = binascii.crc_hqx(header, 0)
    #   - return header + struct.pack(">H", crc) + body
    raise NotImplementedError


def parse_header(header: bytes) -> int:
    """Validate the 4-byte header and return the body length.

    Shared with the demodulator, which needs the length to know how many more
    bits to decode. Raises FramingError on a short header, bad CRC, or a
    length over MAX_BODY.
    """
    # TODO:
    #   - need at least HEADER_BYTES bytes
    #   - unpack length and crc from header[:HEADER_BYTES]
    #   - check the CRC *first*, then the MAX_BODY cap
    raise NotImplementedError


def deframe(data: bytes) -> bytes:
    """Check the header and return exactly `length` bytes of body.

    Raises FramingError on a short header, bad CRC, length over MAX_BODY,
    or fewer than `length` body bytes.
    """
    # TODO:
    #   - length = parse_header(data)
    #   - check enough bytes follow the header, then return data[HEADER_BYTES:HEADER_BYTES + length]
    #   - bytes after the body are ignored
    raise NotImplementedError
