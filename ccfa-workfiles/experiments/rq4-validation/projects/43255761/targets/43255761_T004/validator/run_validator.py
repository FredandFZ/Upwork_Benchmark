#!/usr/bin/env python3
from pathlib import Path
import sys

VALIDATOR_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(VALIDATOR_ROOT))
from validator_core import main

if __name__ == "__main__":
    raise SystemExit(main("43255761_T004"))
