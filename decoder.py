"""
decoder.py — Role 4 integration glue.

Chains the full receive pipeline: demodulate -> deframe -> decrypt.
Returns a small result object so the listener and CLI can print a clean line
and NEVER leak garbled bytes. This is the single place the four modules meet
on the receive side.
"""

from dataclasses import dataclass

import numpy as np

from common import DecryptionError, DemodulationError, FramingError
from crypto import decrypt
from demod import demodulate
from framing import deframe

# One line per failure type, exactly as the task plan specifies.
DISCARD_LINES = {
    "no_signal": "[discarded: no signal decoded]",
    "bad_header": "[discarded: corrupted header]",
    "failed_auth": "[discarded: failed authentication]",
}


def sanitize(text: str) -> str:
    """Replace non-printable characters (newlines, tabs, terminal escapes) with U+FFFD."""
    return "".join(ch if ch.isprintable() else "�" for ch in text)


@dataclass
class DecodeResult:
    ok: bool
    text: str = ""
    reason: str = ""      # one of DISCARD_LINES' keys when not ok

    def line(self) -> str:
        return self.text if self.ok else DISCARD_LINES[self.reason]


def decode(samples: np.ndarray, key: bytes) -> DecodeResult:
    """Run the whole receive pipeline on a buffer of samples."""
    try:
        body = deframe(demodulate(samples))
    except DemodulationError:
        return DecodeResult(ok=False, reason="no_signal")
    except FramingError:  # bad CRC or length, from demodulate's parse_header or deframe
        return DecodeResult(ok=False, reason="bad_header")

    try:
        text = decrypt(body, key)
    except DecryptionError:
        return DecodeResult(ok=False, reason="failed_auth")

    return DecodeResult(ok=True, text=sanitize(text))
