#!/bin/sh
# Only set safe service defaults once. Never change LAN/WAN or existing upgrades.
[ "$(uci -q get firmware-ha.main.initialized)" != 1 ] || exit 0
/etc/init.d/keepalived disable
for service in openvpn ddns-go zerotier frpc; do
    [ ! -x "/etc/init.d/$service" ] || "/etc/init.d/$service" disable
done
# HA stays disabled. Existing network/DHCP and default theme remain upstream defaults.
uci set firmware-ha.main.initialized=1
uci commit firmware-ha
exit 0
