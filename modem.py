"""Transmitter audio: FSK modulation, WAV read/write, playback (Julia).

The receiver side (demodulate) lives in demod.py (Person 3).
"""

import numpy as np

from common import F0, F1, PREAMBLE_BITS, SAMPLE_RATE, SAMPLES_PER_SYMBOL, SYNC_BYTE

# Julia: transmitter audio settings. Keep these local so this work does not
# change the shared constants used by the rest of the project.
FS = SAMPLE_RATE
PREAMBLE_AND_SYNC = np.concatenate(
    (
        np.asarray(PREAMBLE_BITS, dtype=np.uint8),
        np.unpackbits(np.array([SYNC_BYTE], dtype=np.uint8)),
    )
)
_FADE_MS = 5
_LEAD_SILENCE_S = 0.5
_TAIL_SILENCE_S = 0.5
_PEAK_AMPLITUDE = 0.8


# Julia: transmitter audio (modulation, WAV, playback)                        #

def modulate(frame: bytes) -> np.ndarray:
    """Prepend preamble + sync, FSK-modulate, shape, and pad. Returns float32."""
    body_bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8))  # MSB first
    bits = np.concatenate([np.array(PREAMBLE_AND_SYNC, dtype=np.uint8), body_bits])

    freq = np.repeat(np.where(bits == 1, F1, F0), SAMPLES_PER_SYMBOL)
    phase = 2 * np.pi * np.cumsum(freq) / FS          # continuous phase, no clicks
    signal = np.sin(phase)

    # Fade in/out.
    fade = int(FS * _FADE_MS / 1000)
    if fade > 0 and 2 * fade < len(signal):
        ramp = np.linspace(0.0, 1.0, fade)
        signal[:fade] *= ramp
        signal[-fade:] *= ramp[::-1]

    signal *= _PEAK_AMPLITUDE
    lead = np.zeros(int(FS * _LEAD_SILENCE_S))
    tail = np.zeros(int(FS * _TAIL_SILENCE_S))
    return np.concatenate([lead, signal, tail]).astype(np.float32)


def write_wav(path: str, samples: np.ndarray) -> None:
    """Write float audio samples as mono 16-bit PCM at the shared sample rate."""
    import wave

    signal = np.asarray(samples, dtype=np.float32)
    if signal.ndim != 1:
        raise ValueError("expected mono audio samples")

    pcm = (np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(FS)
        wav.writeframes(pcm.tobytes())


def read_wav(path: str) -> np.ndarray:
    """Read mono 16-bit PCM at the shared sample rate into float32 samples."""
    import wave

    with wave.open(path, "rb") as wav:
        if wav.getnchannels() != 1:
            raise ValueError("expected a mono WAV")
        if wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise ValueError("expected 16-bit PCM")
        if wav.getframerate() != FS:
            raise ValueError(f"expected a {FS} Hz WAV")
        frames = wav.readframes(wav.getnframes())

    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def play(samples: np.ndarray, device: int | None = None) -> None:
    """Play samples through sounddevice and block until playback finishes."""
    import sounddevice as sd

    signal = np.asarray(samples, dtype=np.float32)
    if signal.ndim != 1:
        raise ValueError("expected mono audio samples")
    sd.play(signal, FS, device=device)
    sd.wait()
