import binascii
import struct
from pathlib import Path

import numpy as np
import pytest

from common import (
    CRC_INIT,
    DemodulationError,
    FramingError,
    F0,
    F1,
    HEADER_BYTES,
    MAX_BODY,
    MIN_BODY,
    PREAMBLE_BITS,
    SAMPLE_RATE,
    SAMPLES_PER_SYMBOL,
    SYNC_BYTE,
)
from demod import demodulate
from framing import deframe, frame
from modem import modulate, read_wav, write_wav


def modulate_for_test(frame_bytes, *, leading_samples=0):
    frame_bits = np.unpackbits(np.frombuffer(frame_bytes, dtype=np.uint8))
    sync_bits = np.unpackbits(np.array([SYNC_BYTE], dtype=np.uint8))
    bits = np.concatenate((PREAMBLE_BITS, sync_bits, frame_bits))
    frequencies = np.where(bits == 1, F1, F0)
    frequencies = np.repeat(frequencies, SAMPLES_PER_SYMBOL)
    phase = 2 * np.pi * np.cumsum(frequencies) / SAMPLE_RATE
    signal = 0.8 * np.sin(phase)
    return np.concatenate((np.zeros(leading_samples), signal, np.zeros(SAMPLE_RATE // 2)))


@pytest.mark.parametrize(
    ("body_size", "leading_samples"),
    [(MIN_BODY, 0), (30, 137), (MAX_BODY, 997)],
)
def test_demodulate_round_trip(body_size, leading_samples):
    body = np.random.default_rng(body_size).bytes(body_size)
    recording = modulate_for_test(
        frame(body), leading_samples=leading_samples
    )

    decoded_frame = demodulate(recording)

    assert deframe(decoded_frame) == body
    assert len(decoded_frame) == HEADER_BYTES + body_size


@pytest.mark.parametrize("snr_db", [20, 10, 0])
def test_demodulate_with_additive_noise(snr_db):
    body = np.random.default_rng(23).bytes(MIN_BODY)
    recording = modulate_for_test(frame(body), leading_samples=173)
    noise_std = np.sqrt(0.32 / 10 ** (snr_db / 10))
    noisy_recording = recording + np.random.default_rng(snr_db).normal(
        0, noise_std, size=recording.shape
    )

    assert deframe(demodulate(noisy_recording)) == body


@pytest.mark.parametrize("scale", [0.5, 0.1, 0.05])
def test_demodulate_at_reduced_volume(scale):
    body = np.random.default_rng(19).bytes(MIN_BODY)
    recording = modulate_for_test(frame(body), leading_samples=61) * scale

    assert deframe(demodulate(recording)) == body


def test_demodulate_rejects_recording_without_preamble():
    with pytest.raises(DemodulationError, match="preamble"):
        demodulate(np.zeros(SAMPLE_RATE, dtype=np.float32))


def test_demodulate_rejects_truncated_recording():
    recording = modulate_for_test(frame(b"x" * MIN_BODY))
    with pytest.raises(DemodulationError, match="frame was complete"):
        demodulate(recording[: -(SAMPLE_RATE // 2 + SAMPLES_PER_SYMBOL)])


def test_demodulate_propagates_header_crc_error():
    body = b"x" * MIN_BODY
    valid_frame = bytearray(frame(body))
    length_field = struct.pack(">H", len(body))
    valid_frame[2:4] = struct.pack(
        ">H", binascii.crc_hqx(length_field, CRC_INIT) ^ 1
    )

    with pytest.raises(FramingError, match="CRC"):
        demodulate(modulate_for_test(bytes(valid_frame)))


# --- against Julia's real modulate / read_wav ------------------------------ #
REFERENCE_WAV = Path(__file__).resolve().parent.parent / "reference.wav"


@pytest.mark.parametrize("body_size", [MIN_BODY, 29, 100, 257, MAX_BODY])
def test_demodulate_real_modulator(body_size):
    body = np.random.default_rng(body_size + 1).bytes(body_size)
    assert deframe(demodulate(modulate(frame(body)))) == body


def test_demodulate_real_modulator_through_wav(tmp_path):
    body = np.random.default_rng(7).bytes(64)
    path = str(tmp_path / "m.wav")
    write_wav(path, modulate(frame(body)))
    assert deframe(demodulate(read_wav(path))) == body


def test_reference_wav_decodes():
    assert deframe(demodulate(read_wav(str(REFERENCE_WAV)))) == bytes(range(32))


def test_reference_wav_matches_current_modulator(tmp_path):
    # If this fails, modulate changed: regenerate reference.wav (see README)
    fresh = str(tmp_path / "fresh.wav")
    write_wav(fresh, modulate(frame(bytes(range(32)))))
    assert REFERENCE_WAV.read_bytes() == Path(fresh).read_bytes()


def test_demodulate_rejects_pure_noise():
    noise = np.random.default_rng(3).normal(0, 0.1, SAMPLE_RATE * 2)
    with pytest.raises((DemodulationError, FramingError)):
        demodulate(noise)


@pytest.mark.parametrize("bad", [np.zeros((10, 2)), np.array([np.nan] * SAMPLE_RATE),
                                 np.array(["a"] * 10)])
def test_demodulate_rejects_non_audio(bad):
    with pytest.raises(DemodulationError):
        demodulate(bad)


def test_demodulate_rejects_too_short_recording():
    with pytest.raises(DemodulationError, match="preamble"):
        demodulate(np.zeros(100))
