import os
import re
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

import receive
from common import KEY_BYTES, SAMPLE_RATE
from crypto import encrypt, key_fingerprint
from framing import frame
from listener import MAX_RECORD_SECONDS
from modem import modulate, write_wav

RECEIVE = Path(__file__).resolve().parent.parent / "receive.py"
STAMP = r"\[\d\d:\d\d:\d\d\] "


@pytest.fixture
def key():
    return os.urandom(KEY_BYTES)


@pytest.fixture
def key_file(tmp_path, key):
    p = tmp_path / "key.bin"
    p.write_bytes(key)
    p.chmod(0o600)
    return p


def wav_of(tmp_path, msg, key, name="m.wav"):
    path = tmp_path / name
    write_wav(str(path), modulate(frame(encrypt(msg, key))))
    return path


def receive_cli(*args, env=None):
    return subprocess.run([sys.executable, str(RECEIVE), *args], capture_output=True,
                          text=True, env={**os.environ, **(env or {})})


def test_from_wav(tmp_path, key, key_file):
    r = receive_cli("--key", str(key_file), "--from-wav", str(wav_of(tmp_path, "hello 🔐", key)))
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == f"key {key_fingerprint(key)}"
    assert re.fullmatch(STAMP + "hello 🔐", lines[1])


def test_wrong_key(tmp_path, key_file):
    r = receive_cli("--key", str(key_file),
                    "--from-wav", str(wav_of(tmp_path, "secret", os.urandom(KEY_BYTES))))
    assert r.returncode == 0
    assert r.stdout.splitlines()[1] == "[discarded: failed authentication]"
    assert "secret" not in r.stdout


def test_silent_wav(tmp_path, key_file):
    path = tmp_path / "quiet.wav"
    write_wav(str(path), np.zeros(SAMPLE_RATE, dtype=np.float32))
    r = receive_cli("--key", str(key_file), "--from-wav", str(path))
    assert r.stdout.splitlines()[1] == "[discarded: no signal decoded]"


def test_hex_key_from_env(tmp_path, key):
    hex_file = tmp_path / "key.hex"
    hex_file.write_text(key.hex() + "\n")
    hex_file.chmod(0o600)
    r = receive_cli("--from-wav", str(wav_of(tmp_path, "env", key)),
                    env={"FV_KEY_PATH": str(hex_file)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.rstrip().endswith("] env")


@pytest.mark.parametrize("contents", [None, b"short", b"z" * 64])
def test_bad_key_is_one_error_line(tmp_path, contents):
    p = tmp_path / "key.bin"
    if contents is not None:
        p.write_bytes(contents)
    r = receive_cli("--key", str(p), "--from-wav", "unused.wav")
    assert r.returncode == 1
    assert r.stderr.startswith("error:") and "Traceback" not in r.stderr


def test_no_key_at_all(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "FV_KEY_PATH"}
    r = subprocess.run([sys.executable, str(RECEIVE), "--from-wav", "x.wav"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "FV_KEY_PATH" in r.stderr


def test_wrong_sample_rate_wav(tmp_path, key_file):
    import wave
    path = tmp_path / "44k.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 100)
    r = receive_cli("--key", str(key_file), "--from-wav", str(path))
    assert r.returncode == 1
    assert r.stderr.startswith("error:") and "Traceback" not in r.stderr


def test_missing_wav(tmp_path, key_file):
    r = receive_cli("--key", str(key_file), "--from-wav", str(tmp_path / "nope.wav"))
    assert r.returncode == 1 and r.stderr.startswith("error:")


def test_escape_sequences_are_neutralised(tmp_path, key, key_file):
    r = receive_cli("--key", str(key_file),
                    "--from-wav", str(wav_of(tmp_path, "hi\x1b[2J\nthere", key)))
    assert "\x1b" not in r.stdout
    assert r.stdout.splitlines()[1].endswith("] hi\ufffd[2J\ufffdthere")


# --- push-to-listen, in process with a fake sounddevice --------------------- #
@pytest.fixture
def fake_sd(monkeypatch):
    calls = {}

    def rec(frames, samplerate, channels, dtype, device=None):
        calls.update(frames=frames, device=device)
        return np.zeros((frames, 1), dtype=np.float32)

    fake = types.ModuleType("sounddevice")
    fake.rec = rec
    fake.wait = lambda: None
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return calls


def test_record_seconds_default_and_cap(fake_sd, key_file, capsys):
    assert receive.main(["--key", str(key_file), "--record-seconds", "--device", "2"]) == 0
    assert fake_sd == {"frames": 15 * SAMPLE_RATE, "device": 2}
    receive.main(["--key", str(key_file), "--record-seconds", "999"])
    assert fake_sd["frames"] == int(MAX_RECORD_SECONDS * SAMPLE_RATE)
    assert "[discarded: no signal decoded]" in capsys.readouterr().out


def test_save_recordings(fake_sd, key_file, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    receive.main(["--key", str(key_file), "--record-seconds", "1", "--save-recordings"])
    assert len(list((tmp_path / "recordings").glob("*.wav"))) == 1


def test_named_recording_uses_safe_descriptive_filename(
    fake_sd, key_file, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    receive.main(
        [
            "--key",
            str(key_file),
            "--record-seconds",
            "1",
            "--save-recordings",
            "--recording-name",
            "quick brown fox",
        ]
    )
    saved = list((tmp_path / "recordings").glob("*.wav"))
    assert len(saved) == 1
    assert re.fullmatch(r"quick-brown-fox-\d{8}-\d{6}\.wav", saved[0].name)


def test_recordings_are_not_saved_by_default(fake_sd, key_file, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    receive.main(["--key", str(key_file), "--record-seconds", "1"])
    assert not (tmp_path / "recordings").exists()


def test_live_mode_prints_summary_on_ctrl_c(monkeypatch, key_file, capsys):
    def interrupted(self):
        raise KeyboardInterrupt
    monkeypatch.setattr(receive.Listener, "run", interrupted)
    assert receive.main(["--key", str(key_file)]) == 0
    assert "ok=0  no_signal=0" in capsys.readouterr().out
