#!/bin/bash
# Builds the release zip: the asset-free plugin plus the extraction tools.
#
# Deliberately ships no Hollow Knight content. The plugin reads its data from a
# `Godhome` folder beside itself, which setup.py generates from the player's own copy
# of the game - so nobody redistributes Team Cherry's assets, and nobody installing it
# needs the .NET SDK.
set -e
cd "$(dirname "$0")/.."

VER="${1:-v0.1.0-final}"
OUT="/tmp/SilksongGodhome-$VER.zip"

export DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.dotnet}"
export PATH="$DOTNET_ROOT:$PATH"

echo "Building the asset-free plugin..."
rm -rf /tmp/ghbuild
dotnet build -c Release -p:NoAssets=true SilksongGodhome/SilksongGodhome.csproj -o /tmp/ghbuild >/dev/null

cp /tmp/ghbuild/SilksongGodhome.dll release/
rm -rf release/tools
mkdir -p release/tools
cp tools/*.py tools/layouts.json release/tools/
rm -rf release/tools/__pycache__

rm -f "$OUT"
cd release
zip -qr "$OUT" "READ ME FIRST.txt" "INSTALL - Windows.bat" "INSTALL - Mac.command" \
    "INSTALL - Linux.sh" setup.py SilksongGodhome.dll tools -x "*/__pycache__/*"
echo "-> $OUT ($(du -h "$OUT" | cut -f1))"
