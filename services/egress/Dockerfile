FROM alpine:3.22

RUN apk add --no-cache \
    dnsmasq \
    iproute2 \
    iptables \
    tini

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD test -f /run/egress/ready \
        && nslookup -type=a "$(cat /run/egress/health_name)" 127.0.0.1 >/dev/null 2>&1

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]