from __future__ import annotations

import sys

from hkpug_challenge.submission import main


if __name__ == "__main__":
    raise SystemExit(main(["validate-envelope", *sys.argv[1:]]))
