#!/bin/sh
# Called by legacy multi-dial generators before they can change network state.
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
[ "$(get pppoe_sessions || echo single)" = multiple ]
