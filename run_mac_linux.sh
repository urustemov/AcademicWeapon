#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
python3 -m pip install -r requirements.txt
printf '\nOpen http://127.0.0.1:8000 in a browser. Stop with Ctrl+C.\n'
python3 app.py
