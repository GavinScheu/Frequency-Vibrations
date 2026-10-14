"""AES-256-GCM encryption and pre-shared key loading (Jacob)."""

import hashlib
import os
import stat
import struct
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from common import (
    DecryptionError,
    KEY_BYTES,
    KEY_ENV_VAR,
    MAX_BODY,
    MAX_PLAINTEXT,
    MIN_BODY,
    NONCE_BYTES,
    TAG_BYTES,
)

MAX_KEY_FILE = 1024  # a key file is 32 bytes binary or 64 hex chars; refuse to read anything huge


def load_key(path: str | None = None) -> bytes:
    """Read the pre-shared key from `path`, or from $FV_KEY_PATH if no path is given.

    Accepts a 32-byte binary file or a 64-character hex text file (whitespace
    ignored). Raises ValueError unless the result is exactly KEY_BYTES bytes.
    Warns on stderr if the file is readable by other users.
    """
    path = path or os.environ.get(KEY_ENV_VAR)
    if not path:
        raise ValueError(f"no key: pass --key or set {KEY_ENV_VAR}")

    with open(path, "rb") as f:
        raw = f.read(MAX_KEY_FILE + 1)
        mode = os.fstat(f.fileno()).st_mode
    if len(raw) > MAX_KEY_FILE:
        raise ValueError(f"{path}: too large to be a key file")

    if len(raw) == KEY_BYTES:
        key = raw
    else:
        try:
            key = bytes.fromhex(raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError(f"{path}: not a {KEY_BYTES}-byte binary key or a hex key") from None
        if len(key) != KEY_BYTES:
            raise ValueError(f"{path}: hex key is {len(key)} bytes; need {KEY_BYTES}")

    if os.name == "posix" and mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"warning: {path} is accessible by other users; run: chmod 600 {path}", file=sys.stderr)
    return key


def key_fingerprint(key: bytes) -> str:
    """Short SHA-256 fingerprint ('xxxx-xxxx') to check two computers hold the same key."""
    h = hashlib.sha256(key).hexdigest()[:8]
    return f"{h[:4]}-{h[4:]}"


def length_aad(blob_len: int) -> bytes:
    """The 2-byte length field that framing will put in the header, used as GCM aad.

    The body length is fully determined by the plaintext length
    (NONCE_BYTES + len(plaintext) + TAG_BYTES), so both encrypt and decrypt can
    compute it themselves and the agreed signatures don't need an aad argument.
    """
    return struct.pack(">H", blob_len)


def _check_key(key: bytes) -> None:
    # AESGCM silently accepts 16- and 24-byte keys (AES-128/192); insist on AES-256
    if len(key) != KEY_BYTES:
        raise ValueError(f"key is {len(key)} bytes; need {KEY_BYTES}")


def encrypt(plaintext: str, key: bytes) -> bytes:
    """Return nonce + ciphertext + tag.

    Raises ValueError if the UTF-8 encoded message is longer than MAX_PLAINTEXT.
    """
    _check_key(key)
    data = plaintext.encode("utf-8")
    if len(data) > MAX_PLAINTEXT:
        raise ValueError(f"message is {len(data)} bytes in UTF-8; max is {MAX_PLAINTEXT}")
    nonce = os.urandom(NONCE_BYTES)
    aad = length_aad(NONCE_BYTES + len(data) + TAG_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def decrypt(blob: bytes, key: bytes) -> str:
    """Reverse encrypt(). Raises DecryptionError on a wrong key or any tampering."""
    _check_key(key)
    if not MIN_BODY <= len(blob) <= MAX_BODY:
        raise DecryptionError(f"blob is {len(blob)} bytes; must be {MIN_BODY}..{MAX_BODY}")
    nonce, ct = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    try:
        data = AESGCM(key).decrypt(nonce, ct, length_aad(len(blob)))
    except InvalidTag:
        raise DecryptionError("authentication failed (wrong key or corrupted message)") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise DecryptionError("authenticated message is not valid UTF-8") from None
