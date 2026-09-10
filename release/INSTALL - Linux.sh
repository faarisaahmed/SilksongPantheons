#!/bin/bash
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    python3 setup.py
else
    echo
    echo "Python 3 is not installed. Install it with your package manager, e.g."
    echo "  sudo apt install python3 python3-pip"
    echo "then run this again."
    read -r -p "Press Enter to close."
fi
