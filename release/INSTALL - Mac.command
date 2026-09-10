#!/bin/bash
# Double-click this file.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    python3 setup.py
else
    cat <<'MSG'

====================================================================
  Python 3 is not installed.
====================================================================

  This mod needs Python to read Godhome out of your copy of
  Hollow Knight. It is free.

  The quickest way: open the Terminal app and run

      xcode-select --install

  and let it finish. Or download it from
  https://www.python.org/downloads/

  Then double-click this file again.

MSG
    read -r -p "Press Enter to close."
fi
