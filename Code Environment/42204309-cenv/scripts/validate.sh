#!/usr/bin/env bash
set -euo pipefail

forge fmt --check
forge build
forge test -vv
