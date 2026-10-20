"""Generate the 256-bit pre-shared key (Jacob).

Usage: python keygen.py [--hex] [--out PATH] [--force]

Copy the key to the other computer by USB stick (or paste a --hex key between
terminals you control). Never send it over audio or chat, and never commit it.
"""

import argparse
import os
import sys

from common import KEY_BYTES
from crypto import key_fingerprint, warn_if_synced


def write_private(path: str, data: bytes, force: bool) -> None:
    """Create `path` with mode 0600 from the first byte; refuse to overwrite unless force."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    target = path + ".tmp" if force else path
    if force and os.path.exists(target):
        os.remove(target)
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if force:
        os.replace(target, path)  # atomic swap; never a half-written key


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a 256-bit pre-shared key.")
    parser.add_argument("--out", help="output path (default: key.bin, or key.hex with --hex)")
    parser.add_argument("--hex", action="store_true", help="write 64 hex characters instead of raw bytes")
    parser.add_argument("--force", action="store_true", help="overwrite an existing key file")
    args = parser.parse_args()
    out = args.out or ("key.hex" if args.hex else "key.bin")

    key = os.urandom(KEY_BYTES)
    data = (key.hex() + "\n").encode("ascii") if args.hex else key
    try:
        write_private(out, data, args.force)
    except FileExistsError:
        print(f"error: {out} already exists; use --force to replace it "
              "(the other computer will need the new key)", file=sys.stderr)
        return 1

    print(f"wrote {'hex' if args.hex else 'binary'} key to {out} (mode 600)")
    print(f"fingerprint: {key_fingerprint(key)}  (check it matches on the other computer)")
    print("copy it by USB stick; never send it over audio or chat, and never commit it")
    warn_if_synced(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
