#!/bin/sh
# A VRRP MASTER event grants VIPs first. Do not start PPPoE until the old peer releases.
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
load_settings || exit 1
[ "$peer_mode" = dual-path ] || exit 0
[ -s "$HA_KEYS/peer_client" ] && [ -s "$HA_KEYS/peer_known_hosts" ] || { fail 'peer identity is not provisioned'; exit 1; }
deadline=$(($(now)+handoff_timeout))
attempt=0
while [ "$(now)" -le "$deadline" ] && [ "$attempt" -lt "$handoff_timeout" ]; do
    attempt=$((attempt+1))
    # A queued BACKUP/FAULT may already have removed our VIP while this handler waits.
    owns_vip || exit 2
    monitor_healthy || exit 1
    (peer_query "$monitor_peer" || true) > "$HA_RUN/peer_wan.result" &
    query_wan=$!
    (peer_query "$heartbeat_peer" || true) > "$HA_RUN/peer_heartbeat.result" &
    query_heart=$!
    wait "$query_wan"; wait "$query_heart"
    wan_reply=$(cat "$HA_RUN/peer_wan.result"); heart_reply=$(cat "$HA_RUN/peer_heartbeat.result")
    # BUSY/UNKNOWN from either path overrides a RELEASED response from the other.
    case "$wan_reply|$heart_reply" in
        *BUSY*|*UNKNOWN*) :;;
        'HA1 RELEASED|'|'|HA1 RELEASED'|'HA1 RELEASED|HA1 RELEASED')
            sleep "$handoff_delay"
            owns_vip || exit 2
            exit 0;;
        '|')
            if [ "$unreachable_takeover" = 1 ] && [ "$(read_state path_misses 0)" -ge 3 ]; then
                sleep "$handoff_delay"
                owns_vip || exit 2
                monitor_healthy || exit 1
                # A path returning during the delay revokes the unavailable-peer decision.
                [ "$(read_state path_misses 0)" -ge 3 ] && exit 0
            fi;;
    esac
    sleep 1
done
fail 'peer has not confirmed PPPoE release; refusing to dial'
exit 1
