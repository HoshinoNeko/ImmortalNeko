#!/bin/sh
set -eu
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
. "$HA_LIB/lib.sh"
load_settings || { fail 'disabled or invalid UCI settings'; exit 1; }
mkdir -p "$HA_RUN"
chmod 700 "$HA_RUN"
priority=100
[ "$role" = primary ] && priority=200
cat <<EOF
global_defs {
    router_id FW_${role}
    script_user root
    enable_script_security
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
        $vip dev $lan
    }
    track_interface {
        $lan
    }
    track_script {
        local_health
    }
    garp_master_delay 1
    garp_master_repeat 5
    notify_master "$HA_LIB/notify.sh MASTER"
    notify_backup "$HA_LIB/notify.sh BACKUP"
    notify_fault "$HA_LIB/notify.sh FAULT"
    notify_stop "$HA_LIB/notify.sh STOP"
}
EOF
