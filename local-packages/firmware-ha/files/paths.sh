#!/bin/sh
# Probe BOTH paths every cycle; route one stable VRRP endpoint through a live path.
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
load_settings || exit 1
[ "$peer_mode" = dual-path ] || exit 0
mkdir -p "$HA_RUN"
probe_wan() {
    monitor_device && link_up "$monitor_dev" &&
        ping -n -I "$monitor_dev" -c 1 -W 1 "$monitor_peer" >/dev/null 2>&1
}
probe_heartbeat() {
    link_up "$heartbeat" && has_address "$heartbeat" "$heartbeat_source" &&
        ping -n -I "$heartbeat" -c 1 -W 1 "$heartbeat_peer" >/dev/null 2>&1
}
cycle() {
    (if probe_wan; then echo 1; else echo 0; fi) > "$HA_RUN/path_wan.result" &
    wan_probe_pid=$!
    (if probe_heartbeat; then echo 1; else echo 0; fi) > "$HA_RUN/path_heartbeat.result" &
    heart_probe_pid=$!
    wait "$wan_probe_pid"; wait "$heart_probe_pid"
    wan_ok=$(cat "$HA_RUN/path_wan.result"); heart_ok=$(cat "$HA_RUN/path_heartbeat.result")
    previous=$(read_state path_selected none)
    selected=none
    # Stay on a working path; returning links need not disturb election traffic.
    if [ "$previous" = wan ] && [ "$wan_ok" = 1 ]; then selected=wan
    elif [ "$heart_ok" = 1 ]; then selected=heartbeat
    elif [ "$wan_ok" = 1 ]; then selected=wan
    fi
    case "$selected" in
        heartbeat) ip -4 route replace "$peer_ip/32" via "$heartbeat_peer" dev "$heartbeat" src "$source_ip" proto 186;;
        wan) ip -4 route replace "$peer_ip/32" via "$monitor_peer" dev "$wan_l2" src "$source_ip" proto 186;;
        none) ip -4 route replace blackhole "$peer_ip/32" proto 186;;
    esac
    misses=0
    [ "$selected" != none ] || misses=$(($(read_state path_misses 0)+1))
    write_state path_wan "$wan_ok"
    write_state path_heartbeat "$heart_ok"
    write_state path_selected "$selected"
    write_state path_misses "$misses"
    write_state path_checked "$(now)"
}
if [ "${1:-}" = once ]; then cycle; exit 0; fi
cleanup() {
    rm -f "$HA_RUN/monitor_pid"
    ip -4 route del "$peer_ip/32" proto 186 2>/dev/null || true
}
write_state monitor_pid "$$"
trap cleanup EXIT
trap 'exit 0' TERM INT
while :; do cycle; sleep 1; done
