#!/bin/sh
# Runtime primitives, intentionally POSIX sh compatible.
HA_LIB=${HA_LIB:-/usr/libexec/firmware-ha}
HA_RUN=${HA_RUN:-/tmp/firmware-ha}
HA_SYS=${HA_SYS:-/sys/class/net}
HA_INIT=${HA_INIT:-/etc/init.d}
HA_UPTIME=${HA_UPTIME:-/proc/uptime}

fail() { echo "firmware-ha: $*" >&2; return 1; }
now() { cut -d. -f1 "$HA_UPTIME"; }
get() { uci -q get "firmware-ha.main.$1"; }
valid_name() { case "$1" in ''|*[!a-zA-Z0-9_.:-]*) return 1;; esac; }
valid_number() { case "$1" in ''|*[!0-9]*) return 1;; esac; }
valid_ip() {
    echo "$1" | awk -F. 'NF!=4 {exit 1} {for(i=1;i<=4;i++) if($i !~ /^[0-9]+$/ || $i>255) exit 1}'
}
load_settings() {
    enabled=$(get enabled) || return 1
    [ "$enabled" = 1 ] || return 1
    role=$(get role); mode=$(get mode)
    lan=$(get lan_device); election=$(get election_device)
    source_ip=$(get election_source); peer_ip=$(get election_peer)
    vip=$(get vip); wan=$(get wan_interface); wan_l2=$(get wan_l2_device)
    vrid=$(get vrid); preempt_delay=$(get preempt_delay)
    acquire_grace=$(get acquire_grace); retry_base=$(get retry_base); retry_max=$(get retry_max)
    quorum=$(get probe_quorum)
    case "$role" in primary|backup) :;; *) fail 'invalid role'; return 1;; esac
    case "$mode" in cold-pppoe|warm) :;; *) fail 'invalid mode'; return 1;; esac
    for value in "$lan" "$election" "$wan" "$wan_l2"; do
        valid_name "$value" || { fail 'invalid or empty interface name'; return 1; }
    done
    valid_ip "$source_ip" && valid_ip "$peer_ip" || { fail 'invalid election IPv4'; return 1; }
    [ "$source_ip" != "$peer_ip" ] || { fail 'source equals peer'; return 1; }
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
    interfaces=$(get managed_interface || true)
    for value in $interfaces; do
        valid_name "$value" && [ "$value" != "$wan" ] || return 1
        [ "$(uci -q get "network.$value.proto")" = wireguard ] || { fail 'only explicitly named WireGuard interfaces may be managed'; return 1; }
    done
    services=$(get service) || return 1
    for value in $services; do
        valid_name "$value" && [ -x "$HA_INIT/$value" ] || { fail 'missing service executable'; return 1; }
        case "$value" in keepalived|firmware-ha|network|firewall|dropbear) fail 'forbidden managed service'; return 1;; esac
    done
}
read_state() { cat "$HA_RUN/$1" 2>/dev/null || printf '%s\n' "${2:-0}"; }
write_state() { printf '%s\n' "$2" > "$HA_RUN/$1.new" && mv "$HA_RUN/$1.new" "$HA_RUN/$1"; }
link_up() { [ "$(cat "$HA_SYS/$1/carrier" 2>/dev/null)" = 1 ]; }
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
    failed=0
    for service in $services; do "$HA_INIT/$service" stop || failed=1; done
    for interface in $interfaces; do ifdown "$interface" || failed=1; done
    if [ "$mode" = cold-pppoe ]; then ifdown "$wan" || failed=1; fi
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
