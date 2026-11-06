#!/bin/sh
# Register only this service's reload trigger; never modify firewall or network.
uci -q batch <<'EOF'
delete ucitrack.@v2ray_server[-1]
add ucitrack v2ray_server
set ucitrack.@v2ray_server[-1].init=v2ray_server
commit ucitrack
EOF
exit 0
