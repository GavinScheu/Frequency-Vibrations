"""
modem.py — FSK modulate (Person 2) and demodulate (Person 3).

OWNER: Persons 2 & 3. This is a working reference so Role 4's integration,
loopback test, and live listener run end to end before their code lands.
Role 4 depends only on the signatures; swap the internals when the real
transmitter/receiver arrive.
"""

import numpy as np

from common import (
    FS, F0, F1, SAMPLES_PER_SYMBOL,
    PREAMBLE_AND_SYNC, PREAMBLE_MATCH_THRESHOLD,
    FADE_MS, LEAD_SILENCE_S, TAIL_SILENCE_S, PEAK_AMPLITUDE,
)

# Reference correlation vectors for one symbol window (Person 3's detector).
_N = np.arange(SAMPLES_PER_SYMBOL)
_REF0 = np.exp(-2j * np.pi * F0 * _N / FS)
_REF1 = np.exp(-2j * np.pi * F1 * _N / FS)


# --------------------------------------------------------------------------- #
# Person 2: modulate                                                          #
# --------------------------------------------------------------------------- #
def modulate(frame: bytes) -> np.ndarray:
    """Prepend preamble + sync, FSK-modulate, shape, and pad. Returns float32."""
    body_bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8))  # MSB first
    bits = np.concatenate([np.array(PREAMBLE_AND_SYNC, dtype=np.uint8), body_bits])

    freq = np.repeat(np.where(bits == 1, F1, F0), SAMPLES_PER_SYMBOL)
    phase = 2 * np.pi * np.cumsum(freq) / FS          # continuous phase, no clicks
    signal = np.sin(phase)

    # Fade in/out.
    fade = int(FS * FADE_MS / 1000)
    if fade > 0 and 2 * fade < len(signal):
        ramp = np.linspace(0.0, 1.0, fade)
        signal[:fade] *= ramp
        signal[-fade:] *= ramp[::-1]

    signal *= PEAK_AMPLITUDE
    lead = np.zeros(int(FS * LEAD_SILENCE_S))
    tail = np.zeros(int(FS * TAIL_SILENCE_S))
    return np.concatenate([lead, signal, tail]).astype(np.float32)


# --------------------------------------------------------------------------- #
# Person 3: demodulate                                                        #
# --------------------------------------------------------------------------- #
def _bit_at(samples: np.ndarray, start: int) -> int:
    """Decode one symbol window beginning at `start`."""
    w = samples[start:start + SAMPLES_PER_SYMBOL]
    if len(w) < SAMPLES_PER_SYMBOL:
        w = np.pad(w, (0, SAMPLES_PER_SYMBOL - len(w)))
    return 1 if abs(np.dot(w, _REF1)) > abs(np.dot(w, _REF0)) else 0


def _find_preamble(samples: np.ndarray):
    """Return the sample offset where the symbol grid starts, or None."""
    step = max(1, SAMPLES_PER_SYMBOL // 10)
    n_sync = len(PREAMBLE_AND_SYNC)
    needed = n_sync * SAMPLES_PER_SYMBOL
    best_off, best_score = None, -1

    for off in range(0, max(1, len(samples) - needed), step):
        score = sum(
            _bit_at(samples, off + i * SAMPLES_PER_SYMBOL) == PREAMBLE_AND_SYNC[i]
            for i in range(n_sync)
        )
        if score > best_score:
            best_score, best_off = score, off
        if score == n_sync:
            break

    if best_off is None or best_score < PREAMBLE_MATCH_THRESHOLD:
        return None

    # Refine with one-sample steps around the coarse best offset.
    lo = max(0, best_off - step)
    hi = min(len(samples) - needed, best_off + step)
    for off in range(lo, hi + 1):
        score = sum(
            _bit_at(samples, off + i * SAMPLES_PER_SYMBOL) == PREAMBLE_AND_SYNC[i]
            for i in range(n_sync)
        )
        if score > best_score:
            best_score, best_off = score, off
    return best_off


def _read_bits(samples: np.ndarray, start: int, n_bits: int) -> np.ndarray:
    return np.array(
        [_bit_at(samples, start + i * SAMPLES_PER_SYMBOL) for i in range(n_bits)],
        dtype=np.uint8,
    )


class DemodError(Exception):
    """No preamble, truncated recording, etc."""


def demodulate(samples: np.ndarray) -> bytes:
    """Find the preamble, align, and return the frame bytes for deframe()."""
    samples = np.asarray(samples, dtype=np.float64)
    off = _find_preamble(samples)
    if off is None:
        raise DemodError("no preamble found")

    data_start = off + len(PREAMBLE_AND_SYNC) * SAMPLES_PER_SYMBOL

    # Header is 4 bytes = 32 bits: length (16) + header CRC (16).
    header_bits = _read_bits(samples, data_start, 32)
    header = np.packbits(header_bits).tobytes()
    length = int.from_bytes(header[:2], "big")

    total_body_bits = length * 8
    body_start = data_start + 32 * SAMPLES_PER_SYMBOL
    if body_start + total_body_bits * SAMPLES_PER_SYMBOL > len(samples):
        raise DemodError("recording ended before the body was complete")

    body_bits = _read_bits(samples, body_start, total_body_bits)
    body = np.packbits(body_bits).tobytes()
    return header + body
