#!/bin/sh
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
load_settings || exit 1
case "${1:-}" in MASTER|BACKUP|FAULT|STOP) :;; *) exit 2;; esac
mkdir -p "$HA_RUN"
# A single keepalived instance serializes transitions. Refuse overlapping callbacks.
mkdir "$HA_RUN/transition.lock" 2>/dev/null || { fail 'transition already in progress'; exit 1; }
trap 'rmdir "$HA_RUN/transition.lock"' EXIT
old=$(read_state state BACKUP)
write_state state "$1"
case "$1" in
    MASTER)
        write_state acquire_until "$(($(now)+acquire_grace))"
        if [ "$mode" = cold-pppoe ]; then
            if ! ifup "$wan"; then
                quarantine
                stop_managed || true
                exit 1
            fi
        fi
        for interface in $interfaces; do
            if ! ifup "$interface"; then
                touch "$HA_RUN/inhibit"
                stop_managed || true
                exit 1
            fi
        done
        for service in $services; do
            if ! "$HA_INIT/$service" start; then
                touch "$HA_RUN/inhibit"
                stop_managed || true
                fail "service failed: $service"
                exit 1
            fi
        done
        ;;
    FAULT)
        [ "$old" != MASTER ] || quarantine
        if ! stop_managed; then touch "$HA_RUN/inhibit"; exit 1; fi
        ;;
    BACKUP|STOP)
        if ! stop_managed; then touch "$HA_RUN/inhibit"; exit 1; fi
        ;;
esac
logger -t firmware-ha "$old -> $1"
