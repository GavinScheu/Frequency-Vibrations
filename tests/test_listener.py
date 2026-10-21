"""Live listener state machine, driven block by block without a microphone."""

import os
import sys
import types

import numpy as np
import pytest

import listener as listener_module
from common import KEY_BYTES, SAMPLE_RATE
from crypto import encrypt
from decoder import DecodeResult
from framing import frame
from listener import (
    BLOCKSIZE, GATE_MIN_RMS, MAX_RECORD_SECONDS, FailureLog, Listener, record_and_decode,
)
from modem import modulate

KEY = os.urandom(KEY_BYTES)


def blocks(samples):
    for i in range(0, len(samples), BLOCKSIZE):
        yield samples[i:i + BLOCKSIZE]


def quiet(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


@pytest.fixture
def heard():
    messages = []
    lst = Listener(KEY, on_message=messages.append, verbose=False)
    lst.calibrate([quiet(1)])
    return lst, messages


def run(lst, *chunks):
    for chunk in chunks:
        for b in blocks(chunk):
            lst.feed(b)


def test_decodes_one_message(heard):
    lst, messages = heard
    run(lst, quiet(1), modulate(frame(encrypt("hello", KEY))), quiet(1.5))
    assert messages == ["hello"]
    assert lst.state == "IDLE" and lst.failures.ok == 1


def test_decodes_back_to_back_messages(heard):
    lst, messages = heard
    for msg in ("one", "two"):
        run(lst, modulate(frame(encrypt(msg, KEY))), quiet(1.5))
    assert messages == ["one", "two"]


def test_long_message_is_not_cut_off(heard):
    # Regression: the old 3 s sync timeout ended a reception at its first quiet block
    lst, messages = heard
    msg = "x" * 200  # about 19 s of tones
    run(lst, modulate(frame(encrypt(msg, KEY))), quiet(1.5))
    assert messages == [msg]


def test_short_click_returns_to_idle(heard):
    lst, messages = heard
    click = np.full(BLOCKSIZE, 0.5, dtype=np.float32)
    run(lst, click, quiet(1.5))
    assert lst.state == "IDLE"
    assert messages == [] and lst.failures.ok == 0 and not lst.failures.counts


def test_wrong_key_is_counted(heard, capsys):
    lst, messages = heard
    lst.verbose = True
    run(lst, modulate(frame(encrypt("secret", os.urandom(KEY_BYTES)))), quiet(1.5))
    assert messages == []
    assert lst.failures.counts["failed_auth"] == 1
    out = capsys.readouterr().out
    assert "[discarded: failed authentication]" in out and "secret" not in out


def test_stuck_gate_is_capped(heard, monkeypatch):
    lst, _ = heard
    seen = []
    monkeypatch.setattr(listener_module, "decode",
                        lambda buf, key: seen.append(len(buf)) or DecodeResult(False, reason="no_signal"))
    hum = np.full(int((MAX_RECORD_SECONDS + 3) * SAMPLE_RATE), 0.5, dtype=np.float32)
    run(lst, hum)
    assert len(seen) == 1
    assert seen[0] <= (MAX_RECORD_SECONDS + 0.1) * SAMPLE_RATE + BLOCKSIZE


def test_ring_buffer_keeps_the_start(heard):
    # A signal that begins quietly (fade-in) still decodes, since the ring seeds the buffer
    lst, messages = heard
    run(lst, quiet(1), modulate(frame(encrypt("ring", KEY))) * 0.05, quiet(1.5))
    assert messages == ["ring"]


def test_calibrate_uses_room_noise_with_minimum():
    lst = Listener(KEY, verbose=False)
    lst.calibrate([quiet(1)])
    assert lst.noise_floor == GATE_MIN_RMS
    lst.calibrate([np.full(SAMPLE_RATE, 0.01, dtype=np.float32)])
    assert lst.noise_floor == pytest.approx(0.01)
    assert lst.gate == pytest.approx(0.03)


def test_callback_only_queues_first_channel():
    lst = Listener(KEY, verbose=False)
    lst._callback(np.ones((4, 1), dtype=np.float32), 4, None, None)
    assert lst.q.get_nowait().tolist() == [1.0] * 4


def test_failure_log_summary():
    log = FailureLog()
    for r in [DecodeResult(True, "a"), DecodeResult(False, reason="bad_header"),
              DecodeResult(False, reason="bad_header"), DecodeResult(False, reason="failed_auth")]:
        log.record(r)
    assert log.summary() == "ok=1  no_signal=0  bad_header=2  failed_auth=1"


@pytest.fixture
def fake_rec(monkeypatch):
    """A sounddevice whose rec() 'records' a prepared signal."""
    state = {"signal": np.zeros(0, dtype=np.float32), "frames": None}

    def rec(frames, samplerate, channels, dtype, device=None):
        state["frames"] = frames
        out = np.zeros((frames, 1), dtype=np.float32)
        n = min(frames, len(state["signal"]))
        out[:n, 0] = state["signal"][:n]
        return out

    fake = types.ModuleType("sounddevice")
    fake.rec = rec
    fake.wait = lambda: None
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return state


def test_record_and_decode(fake_rec, capsys):
    fake_rec["signal"] = modulate(frame(encrypt("pushed", KEY)))
    result = record_and_decode(KEY, seconds=5)
    assert result.ok and result.text == "pushed"
    assert fake_rec["frames"] == 5 * SAMPLE_RATE
    assert capsys.readouterr().out.rstrip().endswith("] pushed")


def test_record_seconds_are_capped(fake_rec):
    record_and_decode(KEY, seconds=10_000)
    assert fake_rec["frames"] == int(MAX_RECORD_SECONDS * SAMPLE_RATE)


def test_record_and_save(fake_rec, tmp_path, capsys):
    fake_rec["signal"] = modulate(frame(encrypt("saved", KEY)))
    record_and_decode(KEY, seconds=4, save_dir=str(tmp_path / "recordings"))
    saved = list((tmp_path / "recordings").glob("*.wav"))
    assert len(saved) == 1
    assert str(saved[0]) in capsys.readouterr().out
