"""Receive pipeline glue: demodulate -> deframe -> decrypt, with clean failure lines."""

import binascii
import os
import struct

import numpy as np
import pytest

from common import CRC_INIT, KEY_BYTES, SAMPLE_RATE
from crypto import encrypt
from decoder import DecodeResult, decode, sanitize
from framing import frame
from modem import modulate

KEY = os.urandom(KEY_BYTES)


def signal(msg, key=KEY):
    return modulate(frame(encrypt(msg, key)))


@pytest.mark.parametrize("msg", ["hello", "", "héllo 🔐"])
def test_decodes(msg):
    result = decode(signal(msg), KEY)
    assert result == DecodeResult(ok=True, text=msg)
    assert result.line() == msg


def test_silence_is_no_signal():
    result = decode(np.zeros(SAMPLE_RATE, dtype=np.float32), KEY)
    assert result.reason == "no_signal"
    assert result.line() == "[discarded: no signal decoded]"


def test_bad_header_crc_is_corrupted_header():
    f = bytearray(frame(encrypt("hi", KEY)))
    f[2:4] = struct.pack(">H", binascii.crc_hqx(bytes(f[:2]), CRC_INIT) ^ 1)
    result = decode(modulate(bytes(f)), KEY)
    assert result.reason == "bad_header"
    assert result.line() == "[discarded: corrupted header]"


def test_wrong_key_is_failed_authentication():
    result = decode(signal("secret"), os.urandom(KEY_BYTES))
    assert result.reason == "failed_auth"
    assert result.line() == "[discarded: failed authentication]"
    assert "secret" not in result.line()


def test_tampered_body_is_failed_authentication():
    f = bytearray(frame(encrypt("secret", KEY)))
    f[-1] ^= 0x01
    assert decode(modulate(bytes(f)), KEY).reason == "failed_auth"


def test_noise_never_decodes():
    rng = np.random.default_rng(0)
    for _ in range(5):
        assert not decode(rng.normal(0, 0.1, SAMPLE_RATE * 2), KEY).ok


def test_control_characters_are_replaced():
    result = decode(signal("a\nb\tc\x1b[31md\x07"), KEY)
    assert result.ok
    assert result.text == "a�b�c�[31md�"


def test_sanitize_keeps_printable_unicode():
    assert sanitize("café 🛰️ ok") == "café 🛰️ ok"
    assert sanitize("\r‮") == "��"  # carriage return, right-to-left override
