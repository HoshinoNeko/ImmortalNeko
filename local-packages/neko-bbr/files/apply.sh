#!/bin/sh
# Only manage the default TCP congestion-control algorithm, never interfaces/DNS.
set -eu
BBR_RUN=${BBR_RUN:-/var/run/neko-bbr}
fail() { echo "neko-bbr: $*" >&2; exit 1; }
valid_algorithm() { case "$1" in ''|*[!a-zA-Z0-9_]*) return 1;; esac; }

if [ "${1:-}" != --locked ]; then
    case "${1:-apply}" in apply|restore) :;; *) fail 'invalid action';; esac
    [ ! -L "$BBR_RUN" ] || fail 'state directory is a symlink'
    umask 077
    mkdir -p "$BBR_RUN" && chmod 700 "$BBR_RUN" || fail 'cannot create private state'
    for name in previous previous.new lock; do
        [ ! -L "$BBR_RUN/$name" ] && [ ! -d "$BBR_RUN/$name" ] || fail 'invalid state path'
    done
    exec flock -n "$BBR_RUN/lock" "$0" --locked "${1:-apply}"
fi
shift
umask 077
previous_file="$BBR_RUN/previous"

restore_previous() {
    [ -f "$previous_file" ] || return 0
    previous=$(cat "$previous_file")
    valid_algorithm "$previous" || fail 'invalid previous algorithm'
    current=$(sysctl -n net.ipv4.tcp_congestion_control) || fail 'cannot read current algorithm'
    valid_algorithm "$current" || fail 'invalid current algorithm'
    if [ "$current" = bbr ]; then
        available=$(sysctl -n net.ipv4.tcp_available_congestion_control) || fail 'cannot read available algorithms'
        case " $available " in *" $previous "*) :;; *) fail 'previous algorithm is unavailable; state retained';; esac
        sysctl -w "net.ipv4.tcp_congestion_control=$previous" >/dev/null || fail 'cannot restore previous algorithm'
    fi
    rm -f "$previous_file"
}

case "${1:-}" in
    restore) restore_previous; exit 0;;
    apply) :;;
    *) fail 'invalid locked action';;
esac
requested=$(uci -q get 'turboacc.@turboacc[0].bbr_cca' 2>/dev/null || echo 0)
case "$requested" in
    0|false|no|off) restore_previous; exit 0;;
    1|true|yes|on) :;;
    *) fail 'invalid BBR selection';;
esac
modprobe tcp_bbr || fail 'BBR module is unavailable'
available=$(sysctl -n net.ipv4.tcp_available_congestion_control) || fail 'cannot read available algorithms'
case " $available " in *' bbr '*) :;; *) fail 'kernel did not register BBR';; esac
current=$(sysctl -n net.ipv4.tcp_congestion_control) || fail 'cannot read current algorithm'
valid_algorithm "$current" || fail 'invalid current algorithm'
if [ -f "$previous_file" ]; then
    previous=$(cat "$previous_file")
    valid_algorithm "$previous" || fail 'invalid previous algorithm'
fi
if [ ! -f "$previous_file" ] || [ "$current" != bbr ]; then
    printf '%s\n' "$current" > "$BBR_RUN/previous.new"
    mv -f "$BBR_RUN/previous.new" "$previous_file"
fi
if ! sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null; then
    restore_previous
    fail 'cannot select BBR'
fi
