"""
test_loopback.py — Role 4 end-to-end tests (no microphone).

The core gate for M2: send.py -> WAV -> read_wav -> demodulate -> deframe ->
decrypt -> correct plaintext. Run this automatically before any hardware test.
"""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from common import DecryptionError, KEY_BYTES, MAX_PLAINTEXT, SAMPLE_RATE
from crypto import decrypt
from demod import demodulate
from framing import deframe
from modem import read_wav, write_wav

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def key_file(tmp_path):
    p = tmp_path / "k.bin"
    p.write_bytes(os.urandom(KEY_BYTES))
    p.chmod(0o600)
    return p


def cli(script, *args):
    return subprocess.run([sys.executable, str(ROOT / script), *args],
                          capture_output=True, text=True)


def send_to_wav(tmp_path, msg, key_file):
    wav = tmp_path / "tmp.wav"
    r = cli("send.py", msg, "--key", str(key_file), "--out", str(wav))
    assert r.returncode == 0, r.stderr
    assert "stub" not in r.stderr, "send.py fell back to a stub modem"
    return wav


def receive_samples(samples, key):
    return decrypt(deframe(demodulate(samples)), key)


# --- the headline test ------------------------------------------------------ #
@pytest.mark.parametrize("msg", [
    "hello",
    "",
    "The quick brown fox jumps over the lazy dog.",
    "accented: café, naïve, résumé",
    "emoji: 🛰️📡🔊",
    "x" * MAX_PLAINTEXT,          # the largest allowed message
    "é" * (MAX_PLAINTEXT // 2),   # largest in 2-byte UTF-8 characters
])
def test_loopback_roundtrip(tmp_path, key_file, msg):
    wav = send_to_wav(tmp_path, msg, key_file)
    assert receive_samples(read_wav(str(wav)), key_file.read_bytes()) == msg


def test_wrong_key_fails_auth(tmp_path, key_file):
    wav = send_to_wav(tmp_path, "secret", key_file)
    with pytest.raises(DecryptionError):
        receive_samples(read_wav(str(wav)), os.urandom(KEY_BYTES))


def test_cli_to_cli(tmp_path, key_file):
    wav = send_to_wav(tmp_path, "CLI to CLI ✓", key_file)
    r = cli("receive.py", "--key", str(key_file), "--from-wav", str(wav))
    assert r.returncode == 0, r.stderr
    sent_fp = cli("send.py", "x", "--key", str(key_file), "--out", str(tmp_path / "x.wav"))
    assert r.stdout.splitlines()[0].split()[-1] in sent_fp.stdout  # same fingerprint both ends
    assert r.stdout.splitlines()[1].endswith("] CLI to CLI ✓")


def test_cli_to_cli_wrong_key(tmp_path, key_file):
    wav = send_to_wav(tmp_path, "secret", key_file)
    other = tmp_path / "other.bin"
    other.write_bytes(os.urandom(KEY_BYTES))
    other.chmod(0o600)
    r = cli("receive.py", "--key", str(other), "--from-wav", str(wav))
    assert r.stdout.splitlines()[1] == "[discarded: failed authentication]"


# --- robustness through the real WAV path ---------------------------------- #
def through_wav(tmp_path, samples):
    path = str(tmp_path / "channel.wav")
    write_wav(path, samples)
    return read_wav(path)


@pytest.mark.parametrize("snr_db", [20, 10])
def test_survives_noise(tmp_path, key_file, snr_db):
    clean = read_wav(str(send_to_wav(tmp_path, "noisy channel test", key_file)))
    active = clean[np.abs(clean) > 0]
    noise_std = np.sqrt(np.mean(active ** 2) / 10 ** (snr_db / 10))
    noisy = clean + np.random.default_rng(snr_db).normal(0, noise_std, len(clean))
    noisy = through_wav(tmp_path, np.clip(noisy, -1, 1).astype(np.float32))
    assert receive_samples(noisy, key_file.read_bytes()) == "noisy channel test"


@pytest.mark.parametrize("scale", [0.5, 0.1, 0.05])
def test_survives_low_volume(tmp_path, key_file, scale):
    clean = read_wav(str(send_to_wav(tmp_path, "quiet", key_file)))
    assert receive_samples(through_wav(tmp_path, clean * scale), key_file.read_bytes()) == "quiet"


def test_survives_random_leading_silence(tmp_path, key_file):
    clean = read_wav(str(send_to_wav(tmp_path, "padded start", key_file)))
    lead = np.zeros(int(np.random.default_rng(5).integers(1, 3 * SAMPLE_RATE)), dtype=np.float32)
    padded = through_wav(tmp_path, np.concatenate([lead, clean]))
    assert receive_samples(padded, key_file.read_bytes()) == "padded start"
