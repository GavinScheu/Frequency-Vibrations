"""
decoder.py — Role 4 integration glue.

Chains the full receive pipeline: demodulate -> deframe -> decrypt.
Returns a small result object so the listener and CLI can print a clean line
and NEVER leak garbled bytes. This is the single place the four modules meet
on the receive side.
"""

from dataclasses import dataclass

import numpy as np

from framing import deframe, length_aad
from crypto import decrypt, DecryptionError
from modem import demodulate, DemodError
from common import HEADER_BYTES


@dataclass
class DecodeResult:
    ok: bool
    text: str = ""
    reason: str = ""      # one of: "no_preamble", "bad_header", "failed_auth"

    def line(self) -> str:
        if self.ok:
            return self.text
        pretty = {
            "no_preamble": "no preamble found",
            "bad_header": "bad header / framing",
            "failed_auth": "failed authentication",
        }.get(self.reason, self.reason)
        return f"[discarded: {pretty}]"


def decode(samples: np.ndarray) -> DecodeResult:
    """Run the whole receive pipeline on a buffer of samples."""
    # 1. Demodulate audio -> frame bytes.
    try:
        frame_bytes = demodulate(samples)
    except DemodError:
        return DecodeResult(ok=False, reason="no_preamble")

    # 2. Deframe: check header CRC and length, pull out the body.
    try:
        body = deframe(frame_bytes)
    except ValueError:
        return DecodeResult(ok=False, reason="bad_header")

    # 3. Decrypt: the 2-byte length field is the GCM aad.
    aad = length_aad(len(body))
    try:
        from crypto import decrypt as _decrypt  # explicit for clarity
        text = _decrypt(body, _KEY, aad=aad)
    except DecryptionError:
        return DecodeResult(ok=False, reason="failed_auth")

    return DecodeResult(ok=True, text=text)


# The key is injected once at startup so decode() stays a pure-ish function the
# listener can call per buffer without threading the key through every layer.
_KEY = b""


def set_key(key: bytes) -> None:
    global _KEY
    _KEY = key
