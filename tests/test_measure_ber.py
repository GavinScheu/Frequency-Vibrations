import numpy as np

import common
from measure_ber import (
    REFERENCE_BODY,
    bit_error_count,
    compare_phone_recording,
    format_results,
    run_benchmark,
)
import modem
from framing import frame


def test_bit_error_count():
    assert bit_error_count(b"\x00", b"\x03") == 2
    assert bit_error_count(b"\x00", b"\x00\xff") == 8


def test_format_results_includes_errors_and_ber():
    result = format_results(
        [
            {
                "duration_ms": 10,
                "bitrate": 100,
                "snr_db": 20,
                "decoded": 2,
                "failures": 0,
                "trials": 2,
                "bit_errors": 0,
                "compared_bits": 1000,
            }
        ]
    )
    assert "10 ms" in result
    assert "0/1000" in result
    assert "0.000e+00" in result


def test_reference_wav_can_be_compared_without_phone(tmp_path):
    path = tmp_path / "reference.wav"
    expected = frame(REFERENCE_BODY)
    modem.write_wav(str(path), modem.modulate(expected))

    assert compare_phone_recording(str(path)) == (0, len(expected) * 8, 0.0)


def test_benchmark_sweeps_rates_and_restores_shared_constants():
    original = (common.SYMBOL_SECONDS, common.SAMPLES_PER_SYMBOL)

    rows = run_benchmark(trials=1, body_bytes=common.MIN_BODY)

    assert len(rows) == 12
    assert {row["duration_ms"] for row in rows} == {5, 10, 20}
    assert {row["snr_db"] for row in rows} == {None, 0, 10, 20}
    assert (common.SYMBOL_SECONDS, common.SAMPLES_PER_SYMBOL) == original
