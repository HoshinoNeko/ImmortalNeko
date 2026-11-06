#!/bin/sh
set -eu
# Only set safe service defaults once. Never change LAN/WAN or existing upgrades.
[ "$(uci -q get firmware-ha.main.initialized)" != 1 ] || exit 0
HA_INIT=${HA_INIT:-/etc/init.d}
HA_RETAINED_LIST=${HA_RETAINED_LIST:-/etc/firmware-ha/retained-services}
# Validate optional profile data before changing service startup flags.
if [ -f "$HA_RETAINED_LIST" ]; then
    while IFS= read -r service || [ -n "$service" ]; do
        case "$service" in ''|'#'*) continue;; *[!a-zA-Z0-9_-]*) exit 1;; esac
        case "$service" in network|firewall|dropbear|dnsmasq|odhcpd|rpcd|uhttpd|sysntpd|boot|system|cron|done|led|sysctl|sysfixtime|urandom_seed|log|logd|ubus|ubusd) exit 1;; esac
    done < "$HA_RETAINED_LIST"
fi
"$HA_INIT/keepalived" disable
for service in openvpn ddns-go zerotier frpc homeproxy sing-box; do
    [ ! -x "$HA_INIT/$service" ] || "$HA_INIT/$service" disable
done
if [ -f "$HA_RETAINED_LIST" ]; then
    while IFS= read -r service || [ -n "$service" ]; do
        case "$service" in ''|'#'*) continue;; esac
        [ ! -x "$HA_INIT/$service" ] || "$HA_INIT/$service" disable
    done < "$HA_RETAINED_LIST"
fi
# HA stays disabled. Existing network/DHCP and default theme remain upstream defaults.
uci set firmware-ha.main.initialized=1
uci commit firmware-ha
exit 0
