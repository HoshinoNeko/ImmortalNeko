#!/bin/sh
# Server-side forced command. No configuration values or credentials are returned.
set -eu
[ "${SSH_ORIGINAL_COMMAND:-}" = firmware-ha-status-v1 ] || exit 2
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
unknown() { echo 'HA1 UNKNOWN'; exit 0; }
load_settings cleanup >/dev/null 2>&1 || unknown
[ -r "$HA_RUN/config/firmware-ha" ] || unknown
case "$(read_state state UNKNOWN)" in BACKUP|FAULT|STOP) :;; *) echo 'HA1 BUSY'; exit 0;; esac
[ ! -d "$HA_RUN/transition.lock" ] || { echo 'HA1 BUSY'; exit 0; }
owns_vip && { echo 'HA1 BUSY'; exit 0; }
status=$(ubus call "network.interface.$wan" status 2>/dev/null) || unknown
up=$(printf '%s' "$status" | jsonfilter -e '@.up')
pending=$(printf '%s' "$status" | jsonfilter -e '@.pending')
[ "$up" = false ] && [ "$pending" = false ] || { echo 'HA1 BUSY'; exit 0; }
echo 'HA1 RELEASED'
