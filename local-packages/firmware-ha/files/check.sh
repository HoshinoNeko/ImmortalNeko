#!/bin/sh
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
load_settings || exit 1
[ ! -e "$HA_RUN/inhibit" ] || exit 1
link_up "$lan" && link_up "$wan_l2" || exit 1
current=$(now)
[ "$current" -ge "$(read_state retry_after 0)" ] || exit 1
state=$(read_state state BACKUP)
if [ "$state" = MASTER ]; then
    if wan_probe; then
        write_state failures 0
        exit 0
    fi
    # PPPoE handoff is asynchronous; allow modem session release and redial.
    [ "$current" -lt "$(read_state acquire_until 0)" ] && exit 0
    exit 1
fi
if [ "$mode" = warm ]; then wan_probe; exit $?; fi
# Cold standby cannot test a PPPoE session owned by the peer.
# Eligibility permits a timed takeover trial, not a claim of Internet health.
exit 0
