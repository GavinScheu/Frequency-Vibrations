"""Sender-to-receiver pipeline without audio: encrypt -> frame -> deframe -> decrypt."""

import os

import pytest

from common import DecryptionError, FramingError, HEADER_BYTES, KEY_BYTES, MAX_PLAINTEXT
from crypto import decrypt, encrypt
from framing import deframe, frame


@pytest.fixture
def key():
    return os.urandom(KEY_BYTES)


@pytest.mark.parametrize("msg", ["", "hello", "héllo 🔐", "x" * MAX_PLAINTEXT])
def test_round_trip(key, msg):
    assert decrypt(deframe(frame(encrypt(msg, key))), key) == msg


def test_round_trip_with_trailing_bytes(key):
    # The demodulator may return a few extra bytes after the frame
    assert decrypt(deframe(frame(encrypt("hi", key)) + b"\x00" * 5), key) == "hi"


def test_every_bit_flip_is_caught(key):
    f = frame(encrypt("hello", key))
    for i in range(len(f) * 8):
        bad = bytearray(f)
        bad[i // 8] ^= 1 << (i % 8)
        expected = FramingError if i < HEADER_BYTES * 8 else DecryptionError
        with pytest.raises(expected):
            decrypt(deframe(bytes(bad)), key)


def test_wrong_key_is_authentication_failure(key):
    f = frame(encrypt("hello", key))
    with pytest.raises(DecryptionError):
        decrypt(deframe(f), os.urandom(KEY_BYTES))
