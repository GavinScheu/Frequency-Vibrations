"""Offline FSK receiver demodulation (Person 3)."""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from common import (
    DemodulationError,
    F0,
    F1,
    PREAMBLE_BITS,
    SAMPLE_RATE,
    SAMPLES_PER_SYMBOL,
    SYNC_BYTE,
)
from framing import parse_header

_SAMPLE_INDEX = np.arange(SAMPLES_PER_SYMBOL)
_REF0 = np.exp(-2j * np.pi * F0 * _SAMPLE_INDEX / SAMPLE_RATE)
_REF1 = np.exp(-2j * np.pi * F1 * _SAMPLE_INDEX / SAMPLE_RATE)
_SYNC_BITS = np.unpackbits(np.array([SYNC_BYTE], dtype=np.uint8))
_KNOWN_BITS = np.concatenate((np.asarray(PREAMBLE_BITS, dtype=np.uint8), _SYNC_BITS))
_PREAMBLE_SYMBOLS = len(_KNOWN_BITS)
_PREAMBLE_OFFSETS = np.rint(
    np.arange(_PREAMBLE_SYMBOLS) * SAMPLES_PER_SYMBOL / max(1, SAMPLES_PER_SYMBOL // 10)
).astype(np.intp)


def _classify_windows(windows: np.ndarray) -> np.ndarray:
    """Classify a batch of symbol windows by their energy at F0 and F1."""
    energy0 = np.abs(windows @ _REF0)
    energy1 = np.abs(windows @ _REF1)
    return energy1 > energy0


def _find_preamble(samples: np.ndarray) -> int:
    """Find the best coarse preamble alignment, then refine it sample by sample."""
    step = max(1, SAMPLES_PER_SYMBOL // 10)
    needed = _PREAMBLE_SYMBOLS * SAMPLES_PER_SYMBOL
    if len(samples) < needed:
        raise DemodulationError("recording ended before the preamble")

    last_start = len(samples) - needed
    candidate_count = last_start // step + 1
    grid_windows = sliding_window_view(samples, SAMPLES_PER_SYMBOL)[::step]
    grid_bits = np.empty(len(grid_windows), dtype=bool)

    for batch_start in range(0, len(grid_windows), 2048):
        batch_end = min(batch_start + 2048, len(grid_windows))
        grid_bits[batch_start:batch_end] = _classify_windows(
            grid_windows[batch_start:batch_end]
        )

    candidate_indices = np.arange(candidate_count)[:, None] + _PREAMBLE_OFFSETS
    coarse_scores = np.count_nonzero(
        grid_bits[candidate_indices] == _KNOWN_BITS, axis=1
    )
    coarse_start = int(np.argmax(coarse_scores)) * step

    refine_starts = np.arange(
        max(0, coarse_start - step),
        min(last_start, coarse_start + step) + 1,
        dtype=np.intp,
    )
    matches = np.zeros(len(refine_starts), dtype=np.intp)
    confidence = np.zeros(len(refine_starts), dtype=np.float64)
    for symbol, expected in enumerate(_KNOWN_BITS):
        starts = refine_starts + symbol * SAMPLES_PER_SYMBOL
        windows = sliding_window_view(samples, SAMPLES_PER_SYMBOL)[starts]
        energy0 = np.abs(windows @ _REF0)
        energy1 = np.abs(windows @ _REF1)
        decoded = energy1 > energy0
        matches += decoded == expected
        confidence += np.where(expected, energy1 - energy0, energy0 - energy1)

    best = int(np.lexsort((confidence, matches))[-1])
    if matches[best] < _PREAMBLE_SYMBOLS - 2:
        raise DemodulationError("no valid preamble found")
    return int(refine_starts[best])


def _decode_bits(samples: np.ndarray, start: int, count: int) -> bytes:
    end = start + count * SAMPLES_PER_SYMBOL
    if start < 0 or end > len(samples):
        raise DemodulationError("recording ended before the frame was complete")
    windows = sliding_window_view(samples[start:end], SAMPLES_PER_SYMBOL)[
        ::SAMPLES_PER_SYMBOL
    ]
    bits = _classify_windows(windows).astype(np.uint8)
    return np.packbits(bits).tobytes()


def demodulate(samples: np.ndarray) -> bytes:
    """Decode a recording into frame bytes, excluding preamble and sync.

    Raises DemodulationError if a preamble is absent or the recording ends
    before the complete frame. Header validation errors propagate as FramingError.
    """
    audio = np.asarray(samples)
    if (
        audio.ndim != 1
        or not np.issubdtype(audio.dtype, np.number)
        or np.iscomplexobj(audio)
    ):
        raise DemodulationError("recording must be a one-dimensional audio signal")
    if not np.all(np.isfinite(audio)):
        raise DemodulationError("recording contains non-finite samples")
    audio = audio.astype(np.float64, copy=False)

    preamble_start = _find_preamble(audio)
    frame_start = preamble_start + _PREAMBLE_SYMBOLS * SAMPLES_PER_SYMBOL
    header = _decode_bits(audio, frame_start, 32)
    body_length = parse_header(header)
    body = _decode_bits(audio, frame_start + 32 * SAMPLES_PER_SYMBOL, body_length * 8)
    return header + body
