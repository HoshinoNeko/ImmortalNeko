#!/bin/sh
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
case "${1:-}" in
    MASTER) load_settings || exit 1;;
    BACKUP|FAULT|STOP) load_settings cleanup || exit 1;;
    *) exit 2;;
esac
mkdir -p "$HA_RUN"
# The FIFO consumer delivers native events serially. Reject concurrent manual calls.
mkdir "$HA_RUN/transition.lock" 2>/dev/null || { fail 'transition already in progress'; exit 1; }
trap 'rmdir "$HA_RUN/transition.lock"' EXIT
old=$(read_state state BACKUP)
write_state state "$1"
case "$1" in
    MASTER)
        write_state phase acquiring
        # Keep health eligible during the coordinated handoff, then reset PPPoE grace.
        allowance=$acquire_grace
        [ "$peer_mode" != dual-path ] || allowance=$((allowance+60))
        write_state acquire_until "$(($(now)+allowance))"
        if [ "$mode" = cold-pppoe ]; then
            gate=0
            "$HA_LIB/handoff.sh" || gate=$?
            if [ "$gate" != 0 ]; then
                if ! stop_managed; then touch "$HA_RUN/inhibit"; exit 1; fi
                if [ "$gate" = 2 ]; then exit 0; fi
                quarantine
                exit 3
            fi
            if [ "$peer_mode" = dual-path ]; then owns_vip || { stop_managed || true; exit 0; }; fi
            write_state acquire_until "$(($(now)+acquire_grace))"
            if ! ifup "$wan"; then
                quarantine
                if ! stop_managed; then touch "$HA_RUN/inhibit"; exit 1; fi
                exit 3
            fi
        fi
        if [ "$peer_mode" = dual-path ]; then owns_vip || { stop_managed || true; exit 0; }; fi
        write_state phase active
        for interface in $interfaces; do
            if ! ifup "$interface"; then
                touch "$HA_RUN/inhibit"
                stop_managed || true
                exit 1
            fi
        done
        for service in $services; do
            if [ "$peer_mode" = dual-path ]; then owns_vip || { stop_managed || true; exit 0; }; fi
            if ! "$HA_INIT/$service" start; then
                touch "$HA_RUN/inhibit"
                stop_managed || true
                fail "service failed: $service"
                exit 1
            fi
        done
        ;;
    FAULT)
        # Failed acquisition already installed its quarantine before VRRP enters FAULT.
        if [ "$old" = MASTER ] && [ "$(now)" -ge "$(read_state retry_after 0)" ]; then quarantine; fi
        if ! stop_managed; then touch "$HA_RUN/inhibit"; exit 1; fi
        ;;
    BACKUP|STOP)
        if ! stop_managed; then touch "$HA_RUN/inhibit"; exit 1; fi
        ;;
esac
logger -t firmware-ha "$old -> $1"
