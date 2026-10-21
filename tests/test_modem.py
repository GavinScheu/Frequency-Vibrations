import sys
import types
import wave

import numpy as np
import pytest

from common import F0, F1, PREAMBLE_BITS, SAMPLE_RATE, SAMPLES_PER_SYMBOL
from framing import frame
from modem import modulate, play, read_wav, write_wav

LEAD = TAIL = SAMPLE_RATE // 2
FRAME = frame(bytes(range(32)))


def dominant_freq(window):
    spectrum = np.abs(np.fft.rfft(window))
    return np.fft.rfftfreq(len(window), 1 / SAMPLE_RATE)[np.argmax(spectrum)]


def write_raw_wav(path, *, channels=1, width=2, rate=SAMPLE_RATE, frames=b"\x00\x00" * 100):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)


def test_modulate_shape_and_dtype():
    s = modulate(FRAME)
    bits = len(PREAMBLE_BITS) + 8 + len(FRAME) * 8
    assert s.dtype == np.float32
    assert len(s) == LEAD + bits * SAMPLES_PER_SYMBOL + TAIL
    assert np.max(np.abs(s)) == pytest.approx(0.8, abs=0.01)


def test_modulate_pads_with_silence():
    s = modulate(FRAME)
    assert not s[:LEAD].any() and not s[-TAIL:].any()


def test_modulate_fades_in_and_out():
    s = modulate(FRAME)
    assert abs(s[LEAD]) < 0.01 and abs(s[-TAIL - 1]) < 0.01


def test_modulate_has_continuous_phase():
    # Largest possible step for a 3 kHz sine at 0.8 peak, plus a little slack: no clicks
    s = modulate(FRAME)
    assert np.max(np.abs(np.diff(s))) < 0.8 * 2 * np.pi * F1 / SAMPLE_RATE * 1.01


def test_modulate_preamble_tones():
    s = modulate(FRAME)
    for i, bit in enumerate(PREAMBLE_BITS + [0, 1, 1, 1, 1, 1, 1, 0]):  # then sync 0x7E
        start = LEAD + i * SAMPLES_PER_SYMBOL
        assert dominant_freq(s[start:start + SAMPLES_PER_SYMBOL]) == (F1 if bit else F0)


def test_wav_round_trip(tmp_path):
    path = tmp_path / "m.wav"
    s = modulate(FRAME)
    write_wav(str(path), s)
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, SAMPLE_RATE)
    back = read_wav(str(path))
    assert back.dtype == np.float32 and len(back) == len(s)
    assert np.max(np.abs(back - s)) < 2 / 32768


def test_write_wav_clips(tmp_path):
    path = tmp_path / "loud.wav"
    write_wav(str(path), np.array([2.0, -2.0], dtype=np.float32))
    assert np.all(np.abs(read_wav(str(path))) <= 1.0)


def test_write_wav_rejects_stereo_array(tmp_path):
    with pytest.raises(ValueError):
        write_wav(str(tmp_path / "x.wav"), np.zeros((10, 2), dtype=np.float32))


@pytest.mark.parametrize("kwargs", [
    {"channels": 2, "frames": b"\x00\x00" * 200},
    {"width": 1, "frames": b"\x80" * 100},
    {"rate": 44100},
])
def test_read_wav_rejects_wrong_format(tmp_path, kwargs):
    path = tmp_path / "bad.wav"
    write_raw_wav(path, **kwargs)
    with pytest.raises(ValueError):
        read_wav(str(path))


def test_play_blocks_until_done(monkeypatch):
    calls = []
    fake = types.ModuleType("sounddevice")
    fake.play = lambda data, rate, device=None: calls.append(("play", len(data), rate, device))
    fake.wait = lambda: calls.append(("wait",))
    monkeypatch.setitem(sys.modules, "sounddevice", fake)

    play(np.zeros(100, dtype=np.float32), device=3)
    assert calls == [("play", 100, SAMPLE_RATE, 3), ("wait",)]


def test_play_rejects_stereo_array(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", types.ModuleType("sounddevice"))
    with pytest.raises(ValueError):
        play(np.zeros((10, 2), dtype=np.float32))
