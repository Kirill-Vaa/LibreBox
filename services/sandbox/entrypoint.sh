#!/usr/bin/env bash
set -euo pipefail

box_dir=/root/.box
ready_path="${box_dir}/ready"
xvfb_log_path="${box_dir}/logs/xvfb.log"

mkdir -p /opt/state "${box_dir}/logs" /root/data
rm -f "${ready_path}"

display_number="${DISPLAY#:}"
display_number="${display_number%%.*}"
if [[ ! "${display_number}" =~ ^[0-9]+$ ]]; then
    echo "Invalid X display: ${DISPLAY}" >&2
    exit 1
fi

lock_path="/tmp/.X${display_number}-lock"
socket_path="/tmp/.X11-unix/X${display_number}"
if [[ -f "${lock_path}" ]]; then
    lock_pid="$(tr -d '[:space:]' < "${lock_path}")"
    if [[ "${lock_pid}" =~ ^[0-9]+$ ]] && kill -0 "${lock_pid}" 2>/dev/null; then
        echo "X display ${DISPLAY} is owned by live process ${lock_pid}" >&2
        exit 1
    fi

    if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        echo "X display ${DISPLAY} is already responding" >&2
        exit 1
    fi

    rm -f "${lock_path}" "${socket_path}"
fi

xvfb_pid=""

cleanup() {
    rm -f "${ready_path}"
    if [[ -n "${xvfb_pid}" ]]; then
        kill "${xvfb_pid}" 2>/dev/null || true
        wait "${xvfb_pid}" 2>/dev/null || true
        xvfb_pid=""
    fi
    rm -f "${lock_path}" "${socket_path}"
}

trap cleanup EXIT
trap 'exit 0' TERM INT

Xvfb "${DISPLAY}" -screen 0 1920x1080x24 -nolisten tcp > "${xvfb_log_path}" 2>&1 &
xvfb_pid=$!

for ((attempt = 0; attempt < 40; attempt++)); do
    if kill -0 "${xvfb_pid}" 2>/dev/null && xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        touch "${ready_path}"
        xvfb_status=0
        wait "${xvfb_pid}" || xvfb_status=$?
        xvfb_pid=""
        if (( xvfb_status != 0 )); then
            echo "Xvfb on ${DISPLAY} exited with status ${xvfb_status}" >&2
            cat "${xvfb_log_path}" >&2
        fi

        exit "${xvfb_status}"
    fi

    if ! kill -0 "${xvfb_pid}" 2>/dev/null; then
        cat "${xvfb_log_path}" >&2
        exit 1
    fi

    sleep 0.25
done

cat "${xvfb_log_path}" >&2
exit 1