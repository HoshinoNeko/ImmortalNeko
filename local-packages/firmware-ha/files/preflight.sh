#!/bin/sh
# Read-only checks before the HA init service changes existing service ownership.
set -eu
HA_USE_LIVE_CONFIG=1
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
load_settings || exit 1
# Legacy SyncDial must not create additional PPP sessions during single-session HA.
if [ "$sessions" = single ] && uci -q get syncdial.config >/dev/null 2>&1 && \
    [ "$(uci -q get syncdial.config.enabled)" = 1 ]; then
    fail 'disable SyncDial before starting single-session PPPoE HA'; exit 1
fi
[ "$peer_mode" = dual-path ] || exit 0
[ "$election" = lo ] && has_address lo "$source_ip" 32 || { fail 'dual-path needs a stable, locally provisioned loopback /32 source'; exit 1; }
for requirement in "proto:dhcp" "device:$wan_l2" 'auto:1' 'defaultroute:0' 'peerdns:0'; do
    field=${requirement%%:*}; expected=${requirement#*:}
    [ "$(uci -q get "network.$monitor.$field")" = "$expected" ] || { fail "invalid DHCP monitoring interface setting: $field"; exit 1; }
done
[ -s "$HA_KEYS/peer_client" ] && [ -s "$HA_KEYS/peer_known_hosts" ] || { fail 'provision dedicated peer identities locally'; exit 1; }
route=$(ip -4 route show exact "$peer_ip/32")
case " $route " in '  '|*' proto 186 '*) :;; *) fail 'control peer address already has a foreign host route'; exit 1;; esac
# Asymmetric failover paths require loose or disabled reverse-path filtering.
conf=${HA_SYSCTL:-/proc/sys/net/ipv4/conf}
global_rpf=$(cat "$conf/all/rp_filter")
for device in "$wan_l2" "$heartbeat"; do
    device_rpf=$(cat "$conf/$device/rp_filter")
    [ "$global_rpf" -ne 1 ] && [ "$device_rpf" -ne 1 ] || [ "$global_rpf" = 2 ] || [ "$device_rpf" = 2 ] || {
        fail "strict rp_filter prevents dual-path receiving on $device"; exit 1;
    }
done
