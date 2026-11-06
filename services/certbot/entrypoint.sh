#!/bin/sh
set -eu

: "${DOMAIN:?DOMAIN must be set}"
CERTBOT_DRY_RUN="${CERTBOT_DRY_RUN:-0}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
CERTBOT_RENEW_INTERVAL_SECONDS="${CERTBOT_RENEW_INTERVAL_SECONDS:-43200}"

webroot_path=/var/www/certbot
certs_path=/etc/nginx/certs
lineage_path="/etc/letsencrypt/live/${DOMAIN}"

require_public_domain() {
    is_public_domain=false
    case "${DOMAIN}" in
        '' | localhost | *.localhost | *[!A-Za-z0-9.-]*) ;;
        *[!0-9.]*)
            case "${DOMAIN}" in
                *.*) is_public_domain=true ;;
            esac
            ;;
    esac
    if [ "${is_public_domain}" != true ]; then
        echo "DOMAIN=${DOMAIN} cannot get a public certificate, set DOMAIN in .env to a public host name that resolves to this server" >&2
        exit 1
    fi
}

install_certificate() {
    if [ ! -f "${lineage_path}/fullchain.pem" ] || [ ! -f "${lineage_path}/privkey.pem" ]; then
        return 0
    fi
    if cmp -s "${lineage_path}/fullchain.pem" "${certs_path}/fullchain.pem" && cmp -s "${lineage_path}/privkey.pem" "${certs_path}/privkey.pem"; then
        return 0
    fi
    certs_owner="$(stat -c '%u' "${certs_path}")"
    install -m 640 "${lineage_path}/privkey.pem" "${certs_path}/privkey.pem.new"
    install -m 644 "${lineage_path}/fullchain.pem" "${certs_path}/fullchain.pem.new"
    chown "${certs_owner}:0" "${certs_path}/privkey.pem.new" "${certs_path}/fullchain.pem.new"
    mv -f "${certs_path}/privkey.pem.new" "${certs_path}/privkey.pem"
    mv -f "${certs_path}/fullchain.pem.new" "${certs_path}/fullchain.pem"
    echo "Installed the certificate for ${DOMAIN} into ${certs_path}"
}

issue() {
    require_public_domain
    : "${CERTBOT_EMAIL:?CERTBOT_EMAIL must be set in .env or on the make command line}"
    set -- certonly --non-interactive --agree-tos --no-eff-email --keep-until-expiring \
        --webroot --webroot-path "${webroot_path}" \
        --cert-name "${DOMAIN}" --domain "${DOMAIN}" --email "${CERTBOT_EMAIL}"
    if [ "${CERTBOT_DRY_RUN}" = 1 ]; then
        certbot "$@" --dry-run
        echo "Dry run passed, ${DOMAIN} can get a certificate from this server"
        return 0
    fi
    certbot "$@"
    install_certificate
}

stop_renew_loop() {
    if [ -n "${background_pid}" ]; then
        kill "${background_pid}" 2>/dev/null || true
        wait "${background_pid}" 2>/dev/null || true
    fi
    exit 0
}

renew_loop() {
    background_pid=""
    trap stop_renew_loop TERM INT
    while true; do
        if [ ! -f "${lineage_path}/fullchain.pem" ]; then
            echo "No certificate for ${DOMAIN} in /etc/letsencrypt, so nothing is renewed. Run make cert-issue EMAIL=<address>" >&2
        fi
        certbot renew --non-interactive &
        background_pid=$!
        wait "${background_pid}" || echo "certbot renew failed, the next attempt is in ${CERTBOT_RENEW_INTERVAL_SECONDS} seconds" >&2
        install_certificate || echo "Failed to install the certificate for ${DOMAIN} into ${certs_path}" >&2
        sleep "${CERTBOT_RENEW_INTERVAL_SECONDS}" &
        background_pid=$!
        wait "${background_pid}" || true
    done
}

case "${1:-renew-loop}" in
    issue) issue ;;
    renew-loop) renew_loop ;;
    *)
        echo "Unknown command ${1}, use issue or renew-loop" >&2
        exit 1
        ;;
esac