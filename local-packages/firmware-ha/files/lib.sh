#!/bin/sh
# Runtime primitives, intentionally POSIX sh compatible.
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
HA_RUN=${HA_RUN:-/tmp/firmware-ha}
HA_SYS=${HA_SYS:-/sys/class/net}
HA_INIT=${HA_INIT:-/etc/init.d}
HA_UPTIME=${HA_UPTIME:-/proc/uptime}
HA_KEYS=${HA_KEYS:-/etc/firmware-ha}
HA_SSH=${HA_SSH:-/usr/bin/ssh}

fail() { echo "firmware-ha: $*" >&2; return 1; }
now() { cut -d. -f1 "$HA_UPTIME"; }
get() {
    if [ "${HA_USE_LIVE_CONFIG:-0}" != 1 ] && [ -r "$HA_RUN/config/firmware-ha" ]; then
        uci -c "$HA_RUN/config" -q get "firmware-ha.main.$1"
    else
        uci -q get "firmware-ha.main.$1"
    fi
}
valid_name() { case "$1" in ''|*[!a-zA-Z0-9_.:-]*) return 1;; esac; }
valid_number() { case "$1" in ''|*[!0-9]*) return 1;; esac; }
valid_ip() {
    echo "$1" | awk -F. 'NF!=4 {exit 1} {for(i=1;i<=4;i++) if($i !~ /^[0-9]+$/ || $i>255) exit 1}'
}
load_settings() {
    enabled=$(get enabled) || return 1
    if [ "${1:-normal}" != cleanup ]; then [ "$enabled" = 1 ] || return 1; fi
    role=$(get role); mode=$(get mode)
    peer_mode=$(get peer_mode || echo single-path)
    sessions=$(get pppoe_sessions || echo single)
    lan=$(get lan_device); election=$(get election_device)
    source_ip=$(get election_source); peer_ip=$(get election_peer)
    vip=$(get vip); wan=$(get wan_interface); wan_l2=$(get wan_l2_device)
    vrid=$(get vrid); preempt_delay=$(get preempt_delay)
    acquire_grace=$(get acquire_grace); retry_base=$(get retry_base); retry_max=$(get retry_max)
    quorum=$(get probe_quorum)
    case "$role" in primary|backup) :;; *) fail 'invalid role'; return 1;; esac
    case "$mode" in cold-pppoe|warm) :;; *) fail 'invalid mode'; return 1;; esac
    case "$sessions" in single|multiple) :;; *) return 1;; esac
    [ "$mode" != warm ] || [ "$sessions" = multiple ] || { fail 'warm mode requires explicit multiple-session support'; return 1; }
    case "$peer_mode" in single-path|dual-path) :;; *) return 1;; esac
    for value in "$lan" "$election" "$wan" "$wan_l2"; do
        valid_name "$value" || { fail 'invalid or empty interface name'; return 1; }
    done
    valid_ip "$source_ip" && valid_ip "$peer_ip" || { fail 'invalid election IPv4'; return 1; }
    [ "$source_ip" != "$peer_ip" ] || { fail 'source equals peer'; return 1; }
    if [ "$peer_mode" = dual-path ]; then
        monitor=$(get wan_monitor_interface)
        monitor_source=$(get wan_monitor_source); monitor_peer=$(get wan_monitor_peer)
        heartbeat=$(get heartbeat_device)
        heartbeat_source=$(get heartbeat_source); heartbeat_peer=$(get heartbeat_peer)
        peer_port=$(get peer_status_port); handoff_timeout=$(get handoff_timeout); handoff_delay=$(get handoff_delay)
        unreachable_takeover=$(get unreachable_takeover)
        valid_name "$monitor" && valid_name "$heartbeat" && [ "$monitor" != "$wan" ] || return 1
        [ "$heartbeat" != "$wan_l2" ] && [ "$heartbeat" != "$lan" ] && [ "$heartbeat" != lo ] || { fail 'heartbeat must use a separate device'; return 1; }
        for value in "$monitor_source" "$monitor_peer" "$heartbeat_source" "$heartbeat_peer"; do valid_ip "$value" || return 1; done
        for value in "$monitor_source" "$monitor_peer"; do
            case "$value" in 192.168.1.*) :;; *) fail 'WAN monitoring requires 192.168.1.0/24'; return 1;; esac
            [ "${value##*.}" -ge 1 ] && [ "${value##*.}" -le 254 ] || return 1
        done
        distinct=' '
        for value in "$source_ip" "$peer_ip" "$monitor_source" "$monitor_peer" "$heartbeat_source" "$heartbeat_peer" "${vip%/*}"; do
            case "$distinct" in *" $value "*) fail 'control/monitor/VIP addresses must be distinct'; return 1;; esac
            distinct="$distinct$value "
        done
        for value in "$peer_port" "$handoff_timeout" "$handoff_delay"; do valid_number "$value" && [ "$value" -le 65535 ] || return 1; done
        [ "$peer_port" -ge 1 ] && [ "$handoff_timeout" -ge 5 ] && [ "$handoff_timeout" -le 60 ] || return 1
        [ "$handoff_delay" -ge 1 ] && [ "$handoff_delay" -le 10 ] || return 1
        case "$unreachable_takeover" in 0|1) :;; *) return 1;; esac
    fi
    case "$vip" in */*) :;; *) fail 'VIP needs IPv4/prefix'; return 1;; esac
    valid_ip "${vip%/*}" && valid_number "${vip#*/}" && [ "${vip#*/}" -le 32 ] || return 1
    [ "${vip%/*}" != "$source_ip" ] && [ "${vip%/*}" != "$peer_ip" ] || return 1
    for value in "$vrid" "$preempt_delay" "$acquire_grace" "$retry_base" "$retry_max" "$quorum"; do
        valid_number "$value" && [ "$value" -le 86400 ] || { fail 'invalid timer/number'; return 1; }
    done
    [ "$vrid" -ge 1 ] && [ "$vrid" -le 255 ] && [ "$preempt_delay" -le 1000 ] || return 1
    [ "$acquire_grace" -ge 10 ] && [ "$acquire_grace" -le 600 ] || return 1
    [ "$retry_base" -ge 10 ] && [ "$retry_max" -ge "$retry_base" ] || return 1
    probes=$(get probe) || return 1
    count=0
    for value in $probes; do valid_ip "$value" || return 1; count=$((count+1)); done
    [ "$count" -ge 2 ] && [ "$count" -le 3 ] && [ "$quorum" -ge 1 ] && [ "$quorum" -le "$count" ] || return 1
    extra_vips=$(get extra_vip || true)
    seen_ips=" ${vip%/*} "
    for value in $extra_vips; do
        case "$value" in *@*) :;; *) fail 'additional VIP requires address/prefix@device'; return 1;; esac
        extra_address=${value%@*}; extra_device=${value##*@}
        valid_name "$extra_device" || return 1
        case "$extra_address" in */*) :;; *) return 1;; esac
        valid_ip "${extra_address%/*}" && valid_number "${extra_address#*/}" && [ "${extra_address#*/}" -le 32 ] || return 1
        case "$seen_ips" in *" ${extra_address%/*} "*) fail 'duplicate VIP address'; return 1;; esac
        [ "${extra_address%/*}" != "$source_ip" ] && [ "${extra_address%/*}" != "$peer_ip" ] || return 1
        if [ "$peer_mode" = dual-path ]; then
            case "$distinct" in *" ${extra_address%/*} "*) fail 'VIP collides with a monitor address'; return 1;; esac
        fi
        seen_ips="$seen_ips${extra_address%/*} "
    done
    interfaces=$(get managed_interface || true)
    for value in $interfaces; do
        valid_name "$value" && [ "$value" != "$wan" ] || return 1
        if [ "${1:-normal}" != cleanup ]; then
            [ "$(uci -q get "network.$value.proto")" = wireguard ] || { fail 'only explicitly named WireGuard interfaces may be managed'; return 1; }
        fi
    done
    services=$(get service) || return 1
    for value in $services; do
        valid_name "$value" || return 1
        if [ "${1:-normal}" != cleanup ]; then
            [ -x "$HA_INIT/$value" ] || { fail 'missing service executable'; return 1; }
        fi
        case "$value" in keepalived|firmware-ha|network|firewall|dropbear) fail 'forbidden managed service'; return 1;; esac
    done
}
read_state() { cat "$HA_RUN/$1" 2>/dev/null || printf '%s\n' "${2:-0}"; }
write_state() { printf '%s\n' "$2" > "$HA_RUN/$1.new" && mv "$HA_RUN/$1.new" "$HA_RUN/$1"; }
link_up() { [ "$(cat "$HA_SYS/$1/carrier" 2>/dev/null)" = 1 ]; }
has_address() {
    ip -4 -o address show dev "$1" | awk -v address="$2" -v prefix="${3:-}" '{split($4,a,"/"); if(a[1]==address && (prefix=="" || a[2]==prefix)) found=1} END {exit !found}'
}
owns_vip() { has_address "$lan" "${vip%/*}"; }
monitor_device() {
    monitor_status=$(ubus call "network.interface.$monitor" status 2>/dev/null) || return 1
    [ "$(printf '%s' "$monitor_status" | jsonfilter -e '@.up')" = true ] || return 1
    monitor_dev=$(printf '%s' "$monitor_status" | jsonfilter -e '@.l3_device')
    valid_name "$monitor_dev" && [ "$monitor_dev" = "$wan_l2" ] || return 1
    has_address "$monitor_dev" "$monitor_source"
}
monitor_healthy() {
    monitor_pid=$(read_state monitor_pid 0)
    valid_number "$monitor_pid" && [ "$monitor_pid" -gt 1 ] && kill -0 "$monitor_pid" 2>/dev/null || return 1
    stamp=$(read_state path_checked 0)
    valid_number "$stamp" || return 1
    age=$(($(now)-stamp))
    [ "$age" -ge 0 ] && [ "$age" -le 6 ]
}
peer_query() {
    # Dedicated identity only permits peer-status.sh; host identity is pinned on both paths.
    timeout -s KILL 3 "$HA_SSH" -F /dev/null -T -n -i "$HA_KEYS/peer_client" \
        -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
        -o UserKnownHostsFile="$HA_KEYS/peer_known_hosts" -o GlobalKnownHostsFile=/dev/null \
        -o HostKeyAlias=firmware-ha-peer -o ConnectTimeout=2 -o ConnectionAttempts=1 \
        -o LogLevel=ERROR -p "$peer_port" "root@$1" firmware-ha-status-v1 2>/dev/null
}
wan_probe() {
    status=$(ubus call "network.interface.$wan" status 2>/dev/null) || return 1
    [ "$(printf '%s' "$status" | jsonfilter -e '@.up')" = true ] || return 1
    l3=$(printf '%s' "$status" | jsonfilter -e '@.l3_device')
    valid_name "$l3" || return 1
    successes=0
    for address in $probes; do
        # Bind to local WAN. Never count a route through the peer as WAN recovery.
        if ping -n -I "$l3" -c 1 -W 1 "$address" >/dev/null 2>&1; then successes=$((successes+1)); fi
        [ "$successes" -ge "$quorum" ] && return 0
    done
    return 1
}
stop_managed() {
    write_state phase releasing
    failed=0
    # Proxy cleanup can restart DNS. Stop client-facing DHCP/DNS/RA last.
    for service in $services; do
        case "$service" in dnsmasq|odhcpd) continue;; esac
        "$HA_INIT/$service" stop || failed=1
    done
    for interface in $interfaces; do ifdown "$interface" || failed=1; done
    if [ "$mode" = cold-pppoe ]; then ifdown "$wan" || failed=1; fi
    for service in dnsmasq odhcpd; do
        case " $services " in *" $service "*) "$HA_INIT/$service" stop || failed=1;; esac
    done
    return "$failed"
}
quarantine() {
    n=$(read_state failures 0); n=$((n+1))
    delay=$retry_base
    i=1
    while [ "$i" -lt "$n" ] && [ "$delay" -lt "$retry_max" ]; do delay=$((delay*2)); i=$((i+1)); done
    [ "$delay" -le "$retry_max" ] || delay=$retry_max
    write_state failures "$n"
    write_state retry_after "$(($(now)+delay))"
}
