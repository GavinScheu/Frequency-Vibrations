"""
audio_io.py — WAV read/write helpers shared by sender, receiver, and tests.

OWNER: Person 2 owns WAV output; read_wav is added here for Role 4's offline
decode path and the loopback test. Stdlib `wave` only — no extra deps.
"""

import wave
import numpy as np

from common import FS


def write_wav(path: str, signal: np.ndarray, fs: int = FS) -> None:
    """Write mono 16-bit PCM from float samples in [-1, 1]."""
    clipped = np.clip(signal, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())


def read_wav(path: str) -> np.ndarray:
    """Read a mono 16-bit PCM WAV into float samples in [-1, 1]."""
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1:
            raise ValueError("expected a mono WAV")
        if w.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
