"""Sender CLI (Jacob).

Usage: python send.py "hello" --key key.bin --out msg.wav --play

Pipeline: encrypt -> frame -> modulate -> write_wav / play
"""

import argparse
import sys

import numpy as np

from common import SAMPLE_RATE
from crypto import encrypt, key_fingerprint, load_key
from framing import frame

try:
    from modem import modulate, play, write_wav  # Julia's code
except ImportError:
    # Stubs until modem.py lands, so the CLI can be tested end to end.
    def modulate(frame_bytes: bytes) -> np.ndarray:
        return np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1 s of silence

    def write_wav(path: str, samples: np.ndarray) -> None:
        print(f"[stub] would write {len(samples)} samples to {path}")

    def play(samples: np.ndarray, device: int | None = None) -> None:
        print(f"[stub] would play {len(samples) / SAMPLE_RATE:.1f} s of audio")


def main() -> int:
    parser = argparse.ArgumentParser(description="Encrypt a message and send it as FSK audio.")
    parser.add_argument("message")
    parser.add_argument("--key", help="path to key file (default: $FV_KEY_PATH)")
    parser.add_argument("--out", help="write the audio to this WAV file")
    parser.add_argument("--play", action="store_true", help="play the audio through the speaker")
    parser.add_argument("--device", type=int, help="sounddevice output device index")
    args = parser.parse_args()

    if not args.out and not args.play:
        parser.error("nothing to do: give --out, --play, or both")

    try:
        key = load_key(args.key)
        blob = encrypt(args.message, key)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    framed = frame(blob)
    samples = modulate(framed)
    print(f"message {len(args.message.encode('utf-8'))} B, frame {len(framed)} B, "
          f"audio {len(samples) / SAMPLE_RATE:.1f} s, key {key_fingerprint(key)}")

    if args.out:
        write_wav(args.out, samples)
    if args.play:
        play(samples, args.device)
    return 0


if __name__ == "__main__":
    sys.exit(main())
