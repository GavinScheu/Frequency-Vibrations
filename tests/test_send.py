import importlib
import os
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

import send as send_module
from common import KEY_BYTES, MAX_PLAINTEXT
from crypto import decrypt, key_fingerprint
from framing import deframe

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


@pytest.fixture
def reload_send(monkeypatch):
    """Reload send.py against a patched `modem`, then restore the real one."""
    def reload(fake_modem):
        monkeypatch.setitem(sys.modules, "modem", fake_modem)  # None makes the import fail
        return importlib.reload(send_module)
    yield reload
    monkeypatch.undo()
    importlib.reload(send_module)


def test_build_signal_uses_modem(reload_send):
    fake = types.ModuleType("modem")
    fake.modulate = lambda frame_bytes: np.frombuffer(frame_bytes, dtype=np.uint8)
    send = reload_send(fake)
    key = os.urandom(KEY_BYTES)
    framed = send.build_signal("héllo", key).tobytes()
    assert decrypt(deframe(framed), key) == "héllo"


def test_missing_modem_is_announced(reload_send, capsys):
    send = reload_send(None)
    samples = send.build_signal("hi", os.urandom(KEY_BYTES))
    assert not samples.any()
    assert "warning: modulate modem.py failed to import" in capsys.readouterr().err


def test_incomplete_modem_is_announced(reload_send, capsys):
    fake = types.ModuleType("modem")
    fake.modulate = lambda frame_bytes: np.ones(10, dtype=np.float32)
    send = reload_send(fake)
    send.play(send.build_signal("hi", os.urandom(KEY_BYTES)))
    err = capsys.readouterr().err
    assert "warning: play missing from modem.py" in err
    assert "modulate" not in err
