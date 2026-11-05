#!/bin/sh
set -eu
# Read-only SSH inventory, raw data stays in a private local directory.
[ "$#" -eq 2 ] || { echo 'Usage: collect-legacy.sh user@router private/legacy-new' >&2; exit 2; }
case "$1" in -*|*[!a-zA-Z0-9@._:-]*) echo 'Invalid SSH target' >&2; exit 2;; esac
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$2" in private/*) :;; *) echo 'Destination must be inside private/' >&2; exit 2;; esac
case "$2" in *..*) echo 'Unsafe destination' >&2; exit 2;; esac
umask 077
[ ! -e "$root/$2" ] || { echo 'Destination exists' >&2; exit 1; }
mkdir -p "$root/$2"
ssh -o BatchMode=yes -- "$1" 'opkg list-installed' > "$root/$2/opkg-list-installed.txt"
ssh -o BatchMode=yes -- "$1" 'ubus call system board' > "$root/$2/board.json"
ssh -o BatchMode=yes -- "$1" 'cat /proc/meminfo; cat /proc/mtd; ip link show' > "$root/$2/hardware.txt"
ssh -o BatchMode=yes -- "$1" 'tar -C / -czf - etc/config' > "$root/$2/etc-config-private.tar.gz"
echo 'Inventory saved privately. Do not upload the raw configuration archive to GitHub.'
