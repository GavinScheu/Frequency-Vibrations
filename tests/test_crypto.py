import os

import pytest

from common import DecryptionError, KEY_BYTES, MAX_PLAINTEXT, NONCE_BYTES, TAG_BYTES
from crypto import decrypt, encrypt, load_key


@pytest.fixture
def key():
    return os.urandom(KEY_BYTES)


@pytest.mark.parametrize("msg", ["hello", "", "café", "emoji 🔐", "x" * MAX_PLAINTEXT])
def test_round_trip(key, msg):
    assert decrypt(encrypt(msg, key), key) == msg


def test_blob_layout(key):
    blob = encrypt("hello", key)
    assert len(blob) == NONCE_BYTES + len(b"hello") + TAG_BYTES


def test_same_message_gives_different_output(key):
    a, b = encrypt("hello", key), encrypt("hello", key)
    assert a != b
    assert a[:NONCE_BYTES] != b[:NONCE_BYTES]


def test_wrong_key_fails(key):
    blob = encrypt("hello", key)
    with pytest.raises(DecryptionError):
        decrypt(blob, os.urandom(KEY_BYTES))


def test_any_bit_flip_fails(key):
    blob = encrypt("hello", key)
    for i in range(len(blob) * 8):
        tampered = bytearray(blob)
        tampered[i // 8] ^= 1 << (i % 8)
        with pytest.raises(DecryptionError):
            decrypt(bytes(tampered), key)


def test_truncated_blob_fails(key):
    blob = encrypt("hello", key)
    for n in (0, NONCE_BYTES, len(blob) - 1):
        with pytest.raises(DecryptionError):
            decrypt(blob[:n], key)


def test_oversized_message_rejected(key):
    with pytest.raises(ValueError):
        encrypt("x" * (MAX_PLAINTEXT + 1), key)


def test_oversized_counts_utf8_bytes_not_chars(key):
    # "é" is 2 bytes in UTF-8, so this is under the char limit but over the byte limit
    with pytest.raises(ValueError):
        encrypt("é" * (MAX_PLAINTEXT // 2 + 1), key)


def test_load_key_from_path(tmp_path):
    p = tmp_path / "key.bin"
    k = os.urandom(KEY_BYTES)
    p.write_bytes(k)
    assert load_key(str(p)) == k


def test_load_key_from_env(tmp_path, monkeypatch):
    p = tmp_path / "key.bin"
    k = os.urandom(KEY_BYTES)
    p.write_bytes(k)
    monkeypatch.setenv("FV_KEY_PATH", str(p))
    assert load_key() == k


@pytest.mark.parametrize("size", [0, 16, 31, 33, 64])
def test_load_key_wrong_size(tmp_path, size):
    p = tmp_path / "key.bin"
    p.write_bytes(os.urandom(size))
    with pytest.raises(ValueError):
        load_key(str(p))


def test_load_key_missing(monkeypatch):
    monkeypatch.delenv("FV_KEY_PATH", raising=False)
    with pytest.raises((ValueError, FileNotFoundError)):
        load_key()
