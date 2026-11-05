#!/bin/sh
set -eu
# Rendering always validates the proposed live configuration.
HA_USE_LIVE_CONFIG=1
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
load_settings || { fail 'disabled or invalid UCI settings'; exit 1; }
mkdir -p "$HA_RUN"
chmod 700 "$HA_RUN"
priority=100
[ "$role" = primary ] && priority=200
extra_addresses=''
extra_tracks=''
tracked=" $lan "
for entry in $extra_vips; do
    address=${entry%@*}; device=${entry##*@}
    extra_addresses="$extra_addresses
        $address dev $device"
    case "$tracked" in
        *" $device "*) :;;
        *) extra_tracks="$extra_tracks
        $device"; tracked="$tracked$device ";;
    esac
done
cat <<EOF
global_defs {
    router_id FW_${role}
    script_user root
    enable_script_security
    vrrp_notify_fifo "$HA_RUN/events.fifo"
    vrrp_notify_fifo_script "$HA_LIB/events.sh"
    shutdown_script "$HA_LIB/notify.sh STOP"
    shutdown_script_timeout 30
}
vrrp_script local_health {
    script "$HA_LIB/check.sh"
    interval 2
    timeout 5
    fall 3
    rise 5
    weight 0
    init_fail
}
vrrp_instance ROUTER {
    state BACKUP
    interface $election
    unicast_src_ip $source_ip
    unicast_peer {
        $peer_ip
    }
    check_unicast_src
    virtual_router_id $vrid
    priority $priority
    advert_int 1
    preempt_delay $preempt_delay
    virtual_ipaddress {
        $vip dev $lan$extra_addresses
    }
    track_interface {
        $lan$extra_tracks
    }
    track_script {
        local_health
    }
    garp_master_delay 1
    garp_master_repeat 5
}
EOF
