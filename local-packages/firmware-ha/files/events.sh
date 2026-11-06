#!/bin/sh
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
[ "$#" -eq 1 ] && [ "$1" = "$HA_RUN/events.fifo" ] && [ -p "$1" ] || { fail 'expected native event FIFO'; exit 2; }
cleanup() {
    trap - EXIT INT TERM
    rm -f "$HA_RUN/consumer_pid"
    if ! "$HA_LIB/notify.sh" STOP; then
        touch "$HA_RUN/inhibit"
        logger -t firmware-ha 'event consumer stopped; cleanup failed'
    fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM
write_state consumer_pid "$$"
# Keepalived guarantees FIFO delivery order; do not fork one handler per event.
while IFS=' ' read -r type instance state priority extra; do
    [ "$type" = INSTANCE ] && [ "$instance" = '"ROUTER"' ] && [ -z "$extra" ] || continue
    valid_number "$priority" || continue
    case "$state" in MASTER|BACKUP|FAULT|STOP) :;; *) continue;; esac
    result=0
    "$HA_LIB/notify.sh" "$state" || result=$?
    case "$result" in
        0) :;;
        3) logger -t firmware-ha 'handoff deferred; retry quarantine is active';;
        *) touch "$HA_RUN/inhibit"
           logger -t firmware-ha "failed $state transition; eligibility inhibited";;
    esac
done < "$1"
