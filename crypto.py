"""AES-256-GCM encryption and pre-shared key loading (Jacob)."""

import os
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from common import (
    DecryptionError,
    KEY_BYTES,
    KEY_ENV_VAR,
    MAX_PLAINTEXT,
    NONCE_BYTES,
    TAG_BYTES,
)


def load_key(path: str | None = None) -> bytes:
    """Read the pre-shared key from `path`, or from $FV_KEY_PATH if no path is given.

    Raises ValueError unless the file holds exactly KEY_BYTES bytes.
    """
    # TODO:
    #   - fall back to os.environ.get(KEY_ENV_VAR) when path is None; error if neither is set
    #   - read the file as bytes
    #   - raise ValueError if len(key) != KEY_BYTES
    raise NotImplementedError


def length_aad(blob_len: int) -> bytes:
    """The 2-byte length field that framing will put in the header, used as GCM aad.

    The body length is fully determined by the plaintext length
    (NONCE_BYTES + len(plaintext) + TAG_BYTES), so both encrypt and decrypt can
    compute it themselves and the agreed signatures don't need an aad argument.
    """
    return struct.pack(">H", blob_len)


def encrypt(plaintext: str, key: bytes) -> bytes:
    """Return nonce + ciphertext + tag.

    Raises ValueError if the UTF-8 encoded message is longer than MAX_PLAINTEXT.
    """
    # TODO:
    #   - data = plaintext.encode("utf-8"); reject if len(data) > MAX_PLAINTEXT
    #   - nonce = os.urandom(NONCE_BYTES)  (fresh every call, never reused)
    #   - aad = length_aad(NONCE_BYTES + len(data) + TAG_BYTES)
    #   - return nonce + AESGCM(key).encrypt(nonce, data, aad)
    raise NotImplementedError


def decrypt(blob: bytes, key: bytes) -> str:
    """Reverse encrypt(). Raises DecryptionError on a wrong key or any tampering."""
    # TODO:
    #   - raise DecryptionError if blob is shorter than NONCE_BYTES + TAG_BYTES
    #   - nonce, ct = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    #   - aad = length_aad(len(blob))
    #   - AESGCM(key).decrypt(...) inside try/except InvalidTag -> raise DecryptionError
    #   - return the result decoded as UTF-8
    raise NotImplementedError
