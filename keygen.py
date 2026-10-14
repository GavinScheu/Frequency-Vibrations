"""Generate the 256-bit pre-shared key (Jacob).

Usage: python keygen.py [--out key.bin] [--force]

Copy the key to the other computer by USB stick or a one-time paste.
Never send it over audio, and never commit it.
"""

import argparse
import os
import sys

from common import KEY_BYTES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="key.bin")
    parser.add_argument("--force", action="store_true", help="overwrite an existing key file")
    args = parser.parse_args()

    # TODO:
    #   - refuse to overwrite args.out unless --force (losing a key that's already been copied is painful)
    #   - key = os.urandom(KEY_BYTES); write it in binary mode
    #   - os.chmod(args.out, 0o600)
    #   - print where it was written (never print the key itself)
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
