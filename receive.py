"""
receive.py — receiver CLI (Role 4).

    python receive.py --key key.bin [--device N]           # live listen
    python receive.py --key key.bin --record-seconds 15    # push-to-listen
    python receive.py --key key.bin --from-wav msg.wav     # offline decode

Prints the key fingerprint at startup, then each decoded message with a
timestamp. On any failure it prints one clean line (e.g.
"[discarded: failed authentication]") and keeps listening.
"""

import argparse
import sys

from crypto import key_fingerprint, load_key
from decoder import decode
from listener import MAX_RECORD_SECONDS, Listener, record_and_decode, timestamped

RECORDINGS_DIR = "recordings"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Listen for and decrypt FSK audio messages.")
    ap.add_argument("--key", help="path to key file (default: $FV_KEY_PATH)")
    ap.add_argument("--device", type=int, default=None, help="input device index")
    ap.add_argument("--record-seconds", type=float, nargs="?", const=15, default=None,
                    help=f"push-to-listen: record a fixed window (default 15, "
                         f"max {MAX_RECORD_SECONDS:g}), then decode")
    ap.add_argument("--save-recordings", action="store_true",
                    help=f"with --record-seconds, also save the recording into {RECORDINGS_DIR}/")
    ap.add_argument("--recording-name",
                    help="optional label for a saved push-to-listen recording")
    ap.add_argument("--from-wav", default=None,
                    help="decode a WAV file offline instead of using the mic")
    args = ap.parse_args(argv)

    if args.recording_name and (
        args.record_seconds is None or not args.save_recordings
    ):
        ap.error("--recording-name requires --record-seconds and --save-recordings")

    try:
        key = load_key(args.key)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"key {key_fingerprint(key)}")

    # Offline decode of an existing WAV (no mic).
    if args.from_wav:
        from modem import read_wav
        try:
            samples = read_wav(args.from_wav)
        except (OSError, ValueError, EOFError) as e:
            print(f"error: {args.from_wav}: {e}", file=sys.stderr)
            return 1
        result = decode(samples, key)
        print(timestamped(result.text) if result.ok else result.line())
        return 0

    # Push-to-listen fallback.
    if args.record_seconds is not None:
        record_and_decode(key, seconds=args.record_seconds, device=args.device,
                          save_dir=RECORDINGS_DIR if args.save_recordings else None,
                          recording_name=args.recording_name)
        return 0

    # Default: continuous live listening.
    listener = Listener(key, device=args.device)
    try:
        listener.run()
    except KeyboardInterrupt:
        print("\n" + listener.failures.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
