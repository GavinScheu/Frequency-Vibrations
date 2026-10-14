"""Shared constants and interfaces for the whole team.

Change anything here only by team agreement (Step 0 of the task plan).

Interfaces:
    crypto.encrypt(plaintext: str, key: bytes) -> bytes      nonce + ciphertext + tag
    crypto.decrypt(blob: bytes, key: bytes) -> str           raises DecryptionError
    crypto.load_key(path: str | None = None) -> bytes        falls back to $FV_KEY_PATH
    framing.frame(body: bytes) -> bytes                      length + header CRC + body
    framing.parse_header(header: bytes) -> int               body length; raises FramingError
    framing.deframe(data: bytes) -> bytes                    raises FramingError
    modem.modulate(frame: bytes) -> np.ndarray               preamble + sync + frame, float32 samples
    modem.write_wav(path: str, samples: np.ndarray) -> None  mono 16-bit PCM at SAMPLE_RATE
    modem.read_wav(path: str) -> np.ndarray                  float32 in [-1, 1]
    modem.play(samples: np.ndarray, device: int | None = None) -> None
    demod.demodulate(samples: np.ndarray) -> bytes           frame bytes; raises DemodulationError

Every failure a receiver can hit is one of DemodulationError, FramingError,
or DecryptionError, so receive.py catches exactly those three.
"""

# Audio / modem
SAMPLE_RATE = 48000             # Hz; switch everyone to 44100 if a device refuses 48k
F0 = 2000                       # Hz, tone for bit 0
F1 = 3000                       # Hz, tone for bit 1
SYMBOL_SECONDS = 0.010          # 10 ms -> 100 bits/s
SAMPLES_PER_SYMBOL = int(SAMPLE_RATE * SYMBOL_SECONDS)  # 480
PREAMBLE_BITS = [0, 1] * 8      # 16 alternating bits for symbol timing
SYNC_BYTE = 0x7E                # marks the start of the length field
# Bit order: most significant bit first (np.unpackbits / np.packbits default)

# Framing
LENGTH_BYTES = 2                # big-endian body length
CRC_BYTES = 2                   # CRC-16 (binascii.crc_hqx, init 0) over the length field
HEADER_BYTES = LENGTH_BYTES + CRC_BYTES
MAX_BODY = 512                  # reject any length field above this

# Crypto
KEY_BYTES = 32                  # AES-256
NONCE_BYTES = 12                # GCM nonce
TAG_BYTES = 16                  # GCM tag
KEY_ENV_VAR = "FV_KEY_PATH"     # fallback when --key is not given

# Largest plaintext (in UTF-8 bytes) that still fits in one frame
MAX_PLAINTEXT = MAX_BODY - NONCE_BYTES - TAG_BYTES


class DecryptionError(Exception):
    """Wrong key, tampered blob, or corrupted ciphertext."""


class FramingError(Exception):
    """Bad header CRC, length over MAX_BODY, or truncated frame."""


class DemodulationError(Exception):
    """No preamble found, or the recording ended before the frame did."""
