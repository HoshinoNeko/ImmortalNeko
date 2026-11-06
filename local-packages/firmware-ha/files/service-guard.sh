#!/bin/sh
# Patched init scripts call this before starting a service controlled by HA.
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
valid_name "${1:-}" || exit 2
if [ ! -r "$HA_RUN/config/firmware-ha" ]; then
    # A normal non-HA installation keeps the upstream service behavior.
    [ "$(uci -q get firmware-ha.main.enabled 2>/dev/null || echo 0)" = 1 ] || exit 0
fi
load_settings cleanup || exit 1
case " $services " in *" $1 "*) :;; *) exit 0;; esac
[ "$(read_state state STOP)" = MASTER ] && [ ! -e "$HA_RUN/inhibit" ] || exit 1
[ "$(read_state phase releasing)" = active ] || exit 1
consumer=$(read_state consumer_pid 0)
valid_number "$consumer" && [ "$consumer" -gt 1 ] && kill -0 "$consumer" 2>/dev/null || exit 1
owns_vip
