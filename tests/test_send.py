import os
import subprocess
import sys
from pathlib import Path

import pytest

from common import KEY_BYTES, MAX_PLAINTEXT
from crypto import key_fingerprint

SEND = Path(__file__).resolve().parent.parent / "send.py"


@pytest.fixture
def key_file(tmp_path):
    p = tmp_path / "key.bin"
    p.write_bytes(os.urandom(KEY_BYTES))
    p.chmod(0o600)
    return p


def send(*args, env=None):
    return subprocess.run([sys.executable, str(SEND), *args], capture_output=True,
                          text=True, env={**os.environ, **(env or {})})


def test_sends(tmp_path, key_file):
    r = send("héllo 🔐", "--key", str(key_file), "--out", str(tmp_path / "m.wav"))
    assert r.returncode == 0, r.stderr
    assert key_fingerprint(key_file.read_bytes()) in r.stdout
    assert "message 11 B, frame 43 B" in r.stdout  # 4 header + 12 nonce + 11 UTF-8 bytes + 16 tag


def test_key_from_env(tmp_path, key_file):
    r = send("hi", "--out", str(tmp_path / "m.wav"), env={"FV_KEY_PATH": str(key_file)})
    assert r.returncode == 0, r.stderr


def test_message_too_long(tmp_path, key_file):
    r = send("x" * (MAX_PLAINTEXT + 1), "--key", str(key_file), "--out", str(tmp_path / "m.wav"))
    assert r.returncode == 1
    assert r.stderr.startswith("error:") and "Traceback" not in r.stderr


def test_missing_key(tmp_path):
    r = send("hi", "--key", str(tmp_path / "nope.bin"), "--out", str(tmp_path / "m.wav"))
    assert r.returncode == 1
    assert "Traceback" not in r.stderr


def test_nothing_to_do(key_file):
    assert send("hi", "--key", str(key_file)).returncode == 2
