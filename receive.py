"""
receive.py — receiver CLI (Role 4).

    python receive.py --key key.bin [--device N]           # live listen
    python receive.py --key key.bin --record-seconds 15    # push-to-listen
    python receive.py --key key.bin --from-wav msg.wav     # offline decode

Prints each decoded message with a timestamp. On any failure it prints one
clean line (e.g. "[discarded: failed authentication]") and keeps listening.
"""

import argparse

from common import KEY_BYTES
from decoder import set_key, decode
from listener import Listener, record_and_decode


def load_key(path: str) -> bytes:
    with open(path, "rb") as f:
        key = f.read()
    if len(key) != KEY_BYTES:
        raise ValueError(f"key must be {KEY_BYTES} bytes, got {len(key)}")
    return key


def main():
    ap = argparse.ArgumentParser(description="AirWhisper receiver")
    ap.add_argument("--key", required=True, help="path to 32-byte key file")
    ap.add_argument("--device", type=int, default=None, help="input device index")
    ap.add_argument("--record-seconds", type=int, default=None,
                    help="push-to-listen: record a fixed window, then decode")
    ap.add_argument("--save", default=None,
                    help="with --record-seconds, also save the recording to this WAV")
    ap.add_argument("--from-wav", default=None,
                    help="decode a WAV file offline instead of using the mic")
    args = ap.parse_args()

    set_key(load_key(args.key))

    # Offline decode of an existing WAV (no mic).
    if args.from_wav:
        from audio_io import read_wav
        result = decode(read_wav(args.from_wav))
        print(result.line())
        return

    # Push-to-listen fallback.
    if args.record_seconds is not None:
        record_and_decode(seconds=args.record_seconds, device=args.device,
                          save_path=args.save)
        return

    # Default: continuous live listening.
    listener = Listener(device=args.device)
    try:
        listener.run()
    except KeyboardInterrupt:
        print("\n" + listener.failures.summary())


if __name__ == "__main__":
    main()
