"""
test_loopback.py — Role 4 end-to-end tests (no microphone).

The core gate for M2: send.py -> WAV -> decode path -> correct plaintext.
Run this automatically before any hardware test.
"""

import os

import numpy as np
import pytest

from send import build_signal
from audio_io import write_wav, read_wav
from decoder import decode, set_key
from common import FS


KEY = os.urandom(32)
OTHER_KEY = os.urandom(32)


def setup_function(_):
    set_key(KEY)


# --- the headline test ------------------------------------------------------ #
@pytest.mark.parametrize("msg", [
    "hello",
    "",
    "The quick brown fox jumps over the lazy dog.",
    "accented: café, naïve, résumé",
    "emoji: 🛰️📡🔊",
    "x" * 300,
])
def test_loopback_roundtrip(tmp_path, msg):
    wav = tmp_path / "msg.wav"
    write_wav(str(wav), build_signal(msg, KEY))
    result = decode(read_wav(str(wav)))
    assert result.ok, result.reason
    assert result.text == msg


# --- in-memory (no WAV) ----------------------------------------------------- #
def test_loopback_in_memory():
    result = decode(build_signal("direct buffer, no file", KEY))
    assert result.ok and result.text == "direct buffer, no file"


# --- failure handling ------------------------------------------------------- #
def test_wrong_key_fails_auth():
    signal = build_signal("secret", KEY)
    set_key(OTHER_KEY)
    result = decode(signal)
    assert not result.ok and result.reason == "failed_auth"


def test_pure_noise_is_rejected():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.1, FS * 2).astype(np.float32)
    result = decode(noise)
    assert not result.ok  # no_preamble (occasionally bad_header), never a false message


def test_leading_silence_is_tolerated():
    signal = build_signal("padded start", KEY)
    padded = np.concatenate([np.zeros(FS // 2, dtype=np.float32), signal])
    result = decode(padded)
    assert result.ok and result.text == "padded start"


# --- robustness: additive noise -------------------------------------------- #
@pytest.mark.parametrize("snr_db", [20, 10])
def test_survives_moderate_noise(snr_db):
    signal = build_signal("noisy channel test", KEY)
    power = np.mean(signal ** 2)
    noise_power = power / (10 ** (snr_db / 10))
    rng = np.random.default_rng(snr_db)
    noisy = signal + rng.normal(0, np.sqrt(noise_power), len(signal)).astype(np.float32)
    result = decode(noisy)
    assert result.ok and result.text == "noisy channel test"
