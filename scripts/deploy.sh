#!/usr/bin/env bash
# Runs on the Pi: update the checkout and install dependencies into the venv.
set -euo pipefail

cd "$(dirname "$0")/.."

git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
