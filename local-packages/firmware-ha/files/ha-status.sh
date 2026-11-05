#!/bin/sh
printf 'enabled=%s\n' "$(uci -q get firmware-ha.main.enabled)"
for name in state retry_after failures acquire_until consumer_pid; do
    printf '%s=%s\n' "$name" "$(cat "/tmp/firmware-ha/$name" 2>/dev/null || echo unset)"
done
[ ! -e /tmp/firmware-ha/inhibit ] || echo 'inhibited=1 (inspect logread before clearing)'
