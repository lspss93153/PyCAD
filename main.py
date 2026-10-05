# SPDX-License-Identifier: GPL-3.0-only
import sys
from collections.abc import Sequence

from pycad2d.app import run


if __name__ == "__main__":
    argv: Sequence[str] = tuple(sys.argv)
    sys.exit(run(argv))
