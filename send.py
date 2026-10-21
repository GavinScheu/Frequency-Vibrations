"""Sender CLI (Jacob).

Usage: python send.py "hello" --key key.bin --out msg.wav --play

Pipeline: encrypt -> frame -> modulate -> write_wav / play
"""

import argparse
import sys

import numpy as np

from common import HEADER_BYTES, NONCE_BYTES, SAMPLE_RATE, TAG_BYTES
from crypto import encrypt, key_fingerprint, load_key
from framing import frame

try:
    import modem  # Julia's code
    _modem_problem = "missing from modem.py"
except ImportError as e:  # modem.py absent, or present but failing to import
    modem = None
    _modem_problem = f"modem.py failed to import: {e}"


def _stub_warning(name: str) -> None:
    # Loud on stderr, so a stubbed run is never mistaken for real audio
    print(f"warning: {name} {_modem_problem}; using a stub", file=sys.stderr)


# Stubs for whichever modem functions are unavailable, so the CLI can still be tested.
def _stub_modulate(frame_bytes: bytes) -> np.ndarray:
    _stub_warning("modulate")
    return np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1 s of silence


def _stub_write_wav(path: str, samples: np.ndarray) -> None:
    _stub_warning("write_wav")
    print(f"[stub] would write {len(samples)} samples to {path}")


def _stub_play(samples: np.ndarray, device: int | None = None) -> None:
    _stub_warning("play")
    print(f"[stub] would play {len(samples) / SAMPLE_RATE:.1f} s of audio")


modulate = getattr(modem, "modulate", _stub_modulate)
write_wav = getattr(modem, "write_wav", _stub_write_wav)
play = getattr(modem, "play", _stub_play)


def build_signal(message: str, key: bytes) -> np.ndarray:
    """encrypt -> frame -> modulate; the samples send.py would write or play."""
    return modulate(frame(encrypt(message, key)))


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
        samples = build_signal(args.message, key)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    msg_bytes = len(args.message.encode("utf-8"))
    frame_bytes = HEADER_BYTES + NONCE_BYTES + msg_bytes + TAG_BYTES
    print(f"message {msg_bytes} B, frame {frame_bytes} B, "
          f"audio {len(samples) / SAMPLE_RATE:.1f} s, key {key_fingerprint(key)}")

    if args.out:
        write_wav(args.out, samples)
    if args.play:
        play(samples, args.device)
    return 0


if __name__ == "__main__":
    sys.exit(main())
