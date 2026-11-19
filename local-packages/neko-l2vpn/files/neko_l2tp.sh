#!/bin/sh
[ -n "$INCLUDE_ONLY" ] || {
    . /lib/functions.sh
    . /lib/functions/network.sh
    . ../netifd-proto.sh
    init_proto "$@"
}
L2VPN_PYTHON=${L2VPN_PYTHON:-/usr/bin/python3}
L2VPN_HELPER=${L2VPN_HELPER:-/usr/libexec/neko-l2vpn/l2vpn.py}

proto_neko_l2tp_init_config() {
    no_device=1
    available=1
    proto_config_add_string tunlink
    proto_config_add_string ipaddr
    proto_config_add_string peeraddr
    proto_config_add_int tunnel_id
    proto_config_add_int peer_tunnel_id
    proto_config_add_int session_id
    proto_config_add_int peer_session_id
    proto_config_add_int local_port
    proto_config_add_int peer_port
    proto_config_add_int mtu
}

proto_neko_l2tp_setup() {
    local cfg="$1" tunlink ipaddr peeraddr tunnel_id peer_tunnel_id session_id peer_session_id local_port peer_port mtu link
    json_get_vars tunlink ipaddr peeraddr tunnel_id peer_tunnel_id session_id peer_session_id local_port peer_port mtu
    case "$cfg" in ''|*[!a-zA-Z0-9_]*) proto_notify_error "$cfg" INVALID_NAME; return 1;; esac
    case "$tunlink" in ''|*[!a-zA-Z0-9_]*) proto_notify_error "$cfg" INVALID_UNDERLAY; return 1;; esac
    [ "$(uci -q get "network.$tunlink.proto")" = wireguard ] || {
        proto_notify_error "$cfg" WIREGUARD_REQUIRED; return 1;
    }
    ( proto_add_host_dependency "$cfg" "$peeraddr" "$tunlink" )
    network_get_device link "$tunlink" || { proto_notify_error "$cfg" UNDERLAY_DOWN; return 1; }
    "$L2VPN_PYTHON" "$L2VPN_HELPER" l2tp-up --name "$cfg" --underlay "$link" \
        --local "$ipaddr" --peer "$peeraddr" --tunnel-id "$tunnel_id" --peer-tunnel-id "$peer_tunnel_id" \
        --session-id "$session_id" --peer-session-id "$peer_session_id" \
        --local-port "${local_port:-1701}" --peer-port "${peer_port:-1701}" --mtu "$mtu" || {
        proto_notify_error "$cfg" L2TP_SETUP_FAILED; return 1;
    }
    proto_init_update "nl2-$cfg" 1
    proto_send_update "$cfg"
}

proto_neko_l2tp_teardown() {
    "$L2VPN_PYTHON" "$L2VPN_HELPER" l2tp-down --name "$1"
}

[ -n "$INCLUDE_ONLY" ] || add_protocol neko_l2tp
