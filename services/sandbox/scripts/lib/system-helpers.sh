#!/usr/bin/env bash

# shellcheck disable=SC2034
records_dir=/usr/local/share/libre-box

apt_install() {
    apt-get update
    apt-get install -y --no-install-recommends "$@"
}

ensure_locale() {
    if ! locale -a 2>/dev/null | grep -q -i '^en_US\.utf-\?8$'; then
        export LANG=C.UTF-8
    fi
}

list_commands() {
    local directory
    local -a directories
    IFS=: read -r -a directories <<< "${PATH}"
    for directory in "${directories[@]}"; do
        if [[ -d "${directory}" ]]; then
            find -L "${directory}" -maxdepth 1 -type f -perm /111 -printf '%f\n' 2>/dev/null || true
        fi
    done | LC_ALL=C sort -u
}

require_commands() {
    local name
    local -a missing_names=()
    for name in "$@"; do
        if ! command -v "${name}" >/dev/null; then
            missing_names+=("${name}")
        fi
    done
    if (( ${#missing_names[@]} != 0 )); then
        echo "Missing commands after ${step_name}: ${missing_names[*]}" >&2
        return 1
    fi
}