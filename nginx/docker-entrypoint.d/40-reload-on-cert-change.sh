#!/bin/sh
set -eu

certificate_path=/etc/nginx/certs/fullchain.pem
check_interval_seconds="${CERT_CHECK_INTERVAL_SECONDS:-900}"

watch_certificate() {
    known_checksum="$(cksum < "${certificate_path}" 2>/dev/null || true)"
    reported_checksum=""
    while true; do
        sleep "${check_interval_seconds}"
        current_checksum="$(cksum < "${certificate_path}" 2>/dev/null || true)"
        if [ "${current_checksum}" = "${known_checksum}" ]; then
            continue
        fi
        if nginx -t >/dev/null 2>&1; then
            nginx -s reload
            known_checksum="${current_checksum}"
            reported_checksum=""
            echo "Reloaded nginx after ${certificate_path} changed"
        elif [ "${current_checksum}" != "${reported_checksum}" ]; then
            reported_checksum="${current_checksum}"
            echo "${certificate_path} changed but nginx -t fails, the running configuration stays" >&2
        fi
    done
}

watch_certificate </dev/null &