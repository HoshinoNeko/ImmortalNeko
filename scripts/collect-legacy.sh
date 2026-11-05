#!/bin/sh
set -eu
[ "$#" -eq 2 ] || { echo 'Usage: collect-legacy.sh user@router private/legacy-new' >&2; exit 2; }
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$root/scripts/collect_device.py" --host "$1" --output "$2"
