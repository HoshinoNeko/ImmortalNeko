#!/bin/sh
# Register the local BBR apply hook; existing DNS/firewall triggers remain theirs.
uci -q batch <<'EOF'
delete ucitrack.@turboacc[-1]
add ucitrack turboacc
set ucitrack.@turboacc[-1].init=neko-bbr
commit ucitrack
EOF
exit 0
