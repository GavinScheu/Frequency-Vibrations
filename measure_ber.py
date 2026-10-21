"""Measure frame bit errors across symbol durations and simulated noise.

Run `python measure_ber.py` for the offline benchmark. For a phone recording,
first create `reference.wav`, play it through a speaker, record it, then run
`python measure_ber.py --recording phone.wav`.
"""

import argparse
import importlib

import numpy as np

import common

SYMBOL_DURATIONS_MS = (20, 10, 5)
SNR_LEVELS_DB = (None, 20, 10, 0)
DEFAULT_BODY_BYTES = 64
REFERENCE_BODY = bytes(range(32))


def bit_error_count(expected: bytes, actual: bytes) -> int:
    """Count differing bits, treating missing or extra bytes as bit errors."""
    shared_bytes = min(len(expected), len(actual))
    errors = sum(
        (left ^ right).bit_count()
        for left, right in zip(expected[:shared_bytes], actual[:shared_bytes])
    )
    return errors + 8 * abs(len(expected) - len(actual))


def _benchmark_duration(duration_ms, trials, body_bytes, seed):
    import demod
    import modem
    from framing import frame
    from common import DemodulationError, FramingError

    rng = np.random.default_rng(seed + duration_ms)
    decoded = {snr: 0 for snr in SNR_LEVELS_DB}
    failures = {snr: 0 for snr in SNR_LEVELS_DB}
    bit_errors = {snr: 0 for snr in SNR_LEVELS_DB}
    compared_bits = {snr: 0 for snr in SNR_LEVELS_DB}
    original_seconds = common.SYMBOL_SECONDS
    original_samples_per_symbol = common.SAMPLES_PER_SYMBOL

    try:
        common.SYMBOL_SECONDS = duration_ms / 1000
        common.SAMPLES_PER_SYMBOL = round(common.SAMPLE_RATE * common.SYMBOL_SECONDS)
        demod = importlib.reload(demod)
        modem = importlib.reload(modem)

        for _ in range(trials):
            body = rng.bytes(body_bytes)
            expected = frame(body)
            clean_signal = modem.modulate(expected)
            active = clean_signal[np.abs(clean_signal) > 1e-6]
            signal_rms = float(np.sqrt(np.mean(active.astype(np.float64) ** 2)))

            for snr_db in SNR_LEVELS_DB:
                if snr_db is None:
                    received_signal = clean_signal
                else:
                    noise_std = signal_rms / (10 ** (snr_db / 20))
                    noise = rng.normal(0, noise_std, size=len(clean_signal))
                    received_signal = clean_signal + noise.astype(np.float32)
                try:
                    actual = demod.demodulate(received_signal)
                except (DemodulationError, FramingError):
                    failures[snr_db] += 1
                    continue

                decoded[snr_db] += 1
                bit_errors[snr_db] += bit_error_count(expected, actual)
                compared_bits[snr_db] += len(expected) * 8
    finally:
        common.SYMBOL_SECONDS = original_seconds
        common.SAMPLES_PER_SYMBOL = original_samples_per_symbol
        importlib.reload(demod)
        importlib.reload(modem)

    return [
        {
            "duration_ms": duration_ms,
            "bitrate": 1000 // duration_ms,
            "snr_db": snr_db,
            "trials": trials,
            "decoded": decoded[snr_db],
            "failures": failures[snr_db],
            "bit_errors": bit_errors[snr_db],
            "compared_bits": compared_bits[snr_db],
        }
        for snr_db in SNR_LEVELS_DB
    ]


def run_benchmark(trials=5, body_bytes=DEFAULT_BODY_BYTES, seed=2026):
    """Return benchmark rows for the supported experimental symbol durations."""
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if body_bytes < common.MIN_BODY or body_bytes > common.MAX_BODY:
        raise ValueError(
            f"body_bytes must be {common.MIN_BODY}..{common.MAX_BODY}"
        )
    rows = []
    for duration_ms in SYMBOL_DURATIONS_MS:
        rows.extend(_benchmark_duration(duration_ms, trials, body_bytes, seed))
    return rows


def format_results(rows):
    """Render benchmark rows as a Markdown table."""
    lines = [
        "| Symbol | Rate | SNR | Decoded | Frame failures | Bit errors / compared bits | BER |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        snr = "clean" if row["snr_db"] is None else f'{row["snr_db"]} dB'
        ber = (
            "n/a"
            if row["compared_bits"] == 0
            else f'{row["bit_errors"] / row["compared_bits"]:.3e}'
        )
        lines.append(
            f'| {row["duration_ms"]} ms | {row["bitrate"]} bit/s | {snr} '
            f'| {row["decoded"]}/{row["trials"]} '
            f'| {row["failures"]}/{row["trials"]} '
            f'| {row["bit_errors"]}/{row["compared_bits"]} | {ber} |'
        )
    return "\n".join(lines)


def compare_phone_recording(path):
    """Decode a recording of the fixed reference frame and calculate its BER."""
    import demod
    import modem
    from framing import frame

    expected = frame(REFERENCE_BODY)
    received = demod.demodulate(modem.read_wav(path))
    errors = bit_error_count(expected, received)
    total = len(expected) * 8
    ber = errors / total
    return errors, total, ber


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=5, help="trials per SNR and rate")
    parser.add_argument(
        "--body-bytes",
        type=int,
        default=DEFAULT_BODY_BYTES,
        help="random body size for the simulated BER sweep",
    )
    parser.add_argument("--seed", type=int, default=2026, help="reproducible RNG seed")
    parser.add_argument(
        "--make-reference",
        metavar="WAV",
        help="write a known reference transmission WAV for a phone recording",
    )
    parser.add_argument(
        "--recording",
        metavar="WAV",
        help="measure BER for a phone recording of the fixed reference frame",
    )
    args = parser.parse_args()

    if args.make_reference and args.recording:
        parser.error("use --make-reference or --recording, not both")
    if args.make_reference:
        import modem
        from framing import frame

        modem.write_wav(args.make_reference, modem.modulate(frame(REFERENCE_BODY)))
        print(f"Wrote phone-test reference to {args.make_reference}")
        print(
            "Expected frame body: bytes 00..1f. Record the full WAV at 48 kHz, "
            "mono, 16-bit PCM."
        )
        return 0
    if args.recording:
        try:
            errors, total, ber = compare_phone_recording(args.recording)
        except (OSError, ValueError, common.DemodulationError, common.FramingError) as exc:
            parser.exit(1, f"Could not decode phone recording: {exc}\n")
        print("| Recording | Bit errors / total bits | BER |")
        print("|---|---:|---:|")
        print(f"| {args.recording} | {errors}/{total} | {ber:.3e} |")
        return 0

    try:
        rows = run_benchmark(args.trials, args.body_bytes, args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    print(format_results(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
