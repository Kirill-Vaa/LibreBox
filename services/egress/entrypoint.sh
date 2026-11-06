#!/bin/sh
set -eu

: "${SANDBOX_SUBNET:?SANDBOX_SUBNET must be set}"
: "${SANDBOX_GATEWAY_IP:?SANDBOX_GATEWAY_IP must be set}"
: "${EGRESS_INNER_IP:?EGRESS_INNER_IP must be set}"
: "${UPSTREAM_GATEWAY_IP:?UPSTREAM_GATEWAY_IP must be set}"
EGRESS_ALLOW_CIDRS="${EGRESS_ALLOW_CIDRS:-}"
EGRESS_BLOCK_CIDRS="${EGRESS_BLOCK_CIDRS:-}"
EGRESS_HEALTH_NAME="${EGRESS_HEALTH_NAME:-health.egress.internal}"
UPSTREAM_DNS="${UPSTREAM_DNS:-127.0.0.11}"

ready_path=/run/egress/ready
health_name_path=/run/egress/health_name
mkdir -p /run/egress
rm -f "${ready_path}"

inner_interface="$(ip -o -4 addr show | awk -v ip="${EGRESS_INNER_IP}" '$4 ~ "^"ip"/" {print $2; exit}')"
if [ -z "${inner_interface}" ]; then
    echo "No interface holds the egress address ${EGRESS_INNER_IP}" >&2
    exit 1
fi

ip address replace "${SANDBOX_GATEWAY_IP}/32" dev "${inner_interface}"

outer_interface="$(ip -o -4 route show to match "${UPSTREAM_GATEWAY_IP}" scope link | awk 'NR==1 {for (i = 1; i < NF; i++) if ($i == "dev") print $(i + 1)}')"
if [ -z "${outer_interface}" ]; then
    echo "No interface reaches the upstream gateway ${UPSTREAM_GATEWAY_IP}" >&2
    exit 1
fi

ip route replace default via "${UPSTREAM_GATEWAY_IP}" dev "${outer_interface}"

if [ "$(cat /proc/sys/net/ipv4/ip_forward)" != "1" ]; then
    echo "IP forwarding is disabled, so compose must set the net.ipv4.ip_forward sysctl" >&2
    exit 1
fi

iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -F
iptables -X

attach_own_chain() {
    own_table="$1"
    hook_chain="$2"
    egress_chain="$3"
    iptables -t "${own_table}" -N "${egress_chain}" 2>/dev/null || true
    iptables -t "${own_table}" -F "${egress_chain}"
    iptables -t "${own_table}" -C "${hook_chain}" -j "${egress_chain}" 2>/dev/null || iptables -t "${own_table}" -A "${hook_chain}" -j "${egress_chain}"
}

attach_own_chain nat POSTROUTING egress_postrouting
attach_own_chain mangle FORWARD egress_forward

iptables -N egress_reject
iptables -A egress_reject -m limit --limit 5/min --limit-burst 10 -j LOG --log-prefix "egress reject: " --log-level 4
iptables -A egress_reject -j REJECT --reject-with icmp-admin-prohibited

iptables -N egress_drop
iptables -A egress_drop -m limit --limit 5/min --limit-burst 10 -j LOG --log-prefix "egress drop: " --log-level 4
iptables -A egress_drop -j DROP

iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -i "${inner_interface}" -s "${SANDBOX_SUBNET}" -p udp --dport 53 -j ACCEPT
iptables -A INPUT -i "${inner_interface}" -s "${SANDBOX_SUBNET}" -p tcp --dport 53 -j ACCEPT
iptables -A INPUT -i "${inner_interface}" -s "${SANDBOX_SUBNET}" -p icmp --icmp-type echo-request -j ACCEPT
iptables -A INPUT -j egress_drop

iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -i "${inner_interface}" ! -s "${SANDBOX_SUBNET}" -j egress_drop

for blocked_cidr in $(echo "${EGRESS_BLOCK_CIDRS}" | tr ',' ' '); do
    [ -n "${blocked_cidr}" ] || continue
    iptables -A FORWARD -i "${inner_interface}" -d "${blocked_cidr}" -j egress_reject
    echo "Egress blocks ${blocked_cidr}"
done

for allowed_cidr in $(echo "${EGRESS_ALLOW_CIDRS}" | tr ',' ' '); do
    [ -n "${allowed_cidr}" ] || continue
    iptables -A FORWARD -i "${inner_interface}" -d "${allowed_cidr}" -j ACCEPT
    echo "Egress allows ${allowed_cidr}"
done

for private_cidr in \
    0.0.0.0/8 \
    10.0.0.0/8 \
    100.64.0.0/10 \
    127.0.0.0/8 \
    169.254.0.0/16 \
    172.16.0.0/12 \
    192.0.0.0/24 \
    192.168.0.0/16 \
    198.18.0.0/15 \
    224.0.0.0/4 \
    240.0.0.0/4; do
    iptables -A FORWARD -i "${inner_interface}" -d "${private_cidr}" -j egress_reject
done

iptables -A FORWARD -i "${inner_interface}" -o "${outer_interface}" -j ACCEPT
iptables -A FORWARD -i "${inner_interface}" -j egress_drop

iptables -t mangle -A egress_forward -o "${outer_interface}" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
iptables -t nat -A egress_postrouting -s "${SANDBOX_SUBNET}" -o "${outer_interface}" -j MASQUERADE

ipv6_forwarding_path=/proc/sys/net/ipv6/conf/all/forwarding
ipv6_forwarding=0
if [ -r "${ipv6_forwarding_path}" ]; then
    ipv6_forwarding="$(cat "${ipv6_forwarding_path}")"
fi

if ip6tables -L -n >/dev/null 2>&1; then
    for ipv6_table in raw mangle nat filter; do
        ip6tables -t "${ipv6_table}" -F 2>/dev/null || true
        ip6tables -t "${ipv6_table}" -X 2>/dev/null || true
    done
    ip6tables -P INPUT DROP
    ip6tables -P FORWARD DROP
    ip6tables -P OUTPUT DROP
    ip6tables -A INPUT -i lo -j ACCEPT
    ip6tables -A OUTPUT -o lo -j ACCEPT
    echo "Egress drops all IPv6 traffic"
elif [ "${ipv6_forwarding}" != "0" ]; then
    echo "IPv6 forwarding is enabled but ip6tables is unusable, so the sandbox would get an unfiltered IPv6 path" >&2
    exit 1
else
    echo "Egress found no usable ip6tables, IPv6 forwarding is off so IPv6 cannot be routed"
fi

set -- --keep-in-foreground --no-resolv --no-hosts --bind-dynamic \
    --listen-address="${SANDBOX_GATEWAY_IP}" --listen-address=127.0.0.1 \
    --stop-dns-rebind --cache-size=1000 \
    --host-record="${EGRESS_HEALTH_NAME},127.0.0.1"
for upstream_server in $(echo "${UPSTREAM_DNS}" | tr ',' ' '); do
    [ -n "${upstream_server}" ] || continue
    if ! echo "${upstream_server}" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}(#[0-9]{1,5})?$'; then
        echo "UPSTREAM_DNS entry '${upstream_server}' is not an IPv4 address with an optional #port" >&2
        exit 1
    fi
    set -- "$@" --server="${upstream_server}"
done

echo "Egress gateway ready inner=${inner_interface} outer=${outer_interface} subnet=${SANDBOX_SUBNET}"
printf '%s' "${EGRESS_HEALTH_NAME}" > "${health_name_path}"
touch "${ready_path}"

exec dnsmasq "$@"