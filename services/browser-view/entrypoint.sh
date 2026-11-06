#!/bin/sh
set -eu

display_number="${DISPLAY#:}"
display_number="${display_number%%.*}"
case "${display_number}" in
    '' | *[!0-9]*)
        echo "Invalid X display: ${DISPLAY}" >&2
        exit 1
        ;;
esac

socket_path="/tmp/.X11-unix/X${display_number}"
idle_screen_path=/usr/share/libre-box/idle-screen.png
retry_delay_seconds=2
max_retry_delay_seconds=30

serve_display() {
    is_waiting_reported=false
    while true; do
        if [ -S "${socket_path}" ] && xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
            echo "Display ${DISPLAY} is up, starting x11vnc"
            is_waiting_reported=false
            retry_delay_seconds=2
            xwallpaper --zoom "${idle_screen_path}" >/dev/null 2>&1 || echo "Failed to set the idle screen on ${DISPLAY}" >&2
            x11vnc -display "${DISPLAY}" -rfbport 5900 -rfbportv6 -1 -localhost -noipv6 \
                -shared -forever -nopw -norc -noremote -nocmds -nolookup \
                -noshm -xkb -quiet -desktop "LibreBox browser" >/dev/null 2>&1 || true
            echo "x11vnc lost display ${DISPLAY}, waiting for it to come back" >&2
        elif [ "${is_waiting_reported}" = false ]; then
            echo "Waiting for display ${DISPLAY}" >&2
            is_waiting_reported=true
        fi
        sleep "${retry_delay_seconds}"
        retry_delay_seconds=$((retry_delay_seconds * 2))
        if [ "${retry_delay_seconds}" -gt "${max_retry_delay_seconds}" ]; then
            retry_delay_seconds="${max_retry_delay_seconds}"
        fi
    done
}

serve_display &

exec websockify --web /srv/web --file-only --heartbeat 30 0.0.0.0:6080 127.0.0.1:5900