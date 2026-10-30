#!/usr/bin/env bash

source /build/lib/system-helpers.sh

exported_paths=()

by_architecture() {
    case "$(dpkg --print-architecture)" in
        amd64) echo "$1" ;;
        arm64) echo "$2" ;;
        *)
            echo "Unsupported architecture: $(dpkg --print-architecture)" >&2
            return 1
            ;;
    esac
}

clone_repository() {
    local url="$1"
    local destination="$2"
    local tag="${3:-}"
    local -a branch_arguments=()
    if [[ -n "${tag}" ]]; then
        branch_arguments=(--branch "${tag}")
    fi
    git -c advice.detachedHead=false clone --quiet --depth 1 "${branch_arguments[@]}" "${url}" "${destination}"
    rm -rf "${destination}/.git"
}

download() {
    local url="$1"
    local path="$2"
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --speed-limit 1024 --speed-time 60 -o "${path}" "${url}"
}

export_path() {
    exported_paths+=("$@")
}

fetch() {
    local url="$1"
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 300 "${url}"
}

freeze_pytools() {
    uv pip freeze --python /opt/pytools/bin/python | grep -v -E '^(pip|setuptools|wheel)==' > /opt/pytools/constraints.txt
    printf '[global]\nconstraint = /opt/pytools/constraints.txt' > /opt/pytools/pip.conf
    remove_bytecode /opt/pytools
}

install_crate() {
    local crate="$1"
    local target_dir="${XDG_CACHE_HOME}/cargo-target"
    /opt/cargo/bin/cargo-binstall --no-confirm --disable-telemetry "${crate}" \
        || CARGO_TARGET_DIR="${target_dir}" /opt/cargo/bin/cargo install --locked "${crate}" \
        || CARGO_TARGET_DIR="${target_dir}" /opt/cargo/bin/cargo install "${crate}"
}

install_optional() {
    local category="$1"
    local package="$2"
    shift 2
    local status="installed"
    "$@" &
    if ! wait "$!"; then
        status="skipped"
        echo "WARNING: optional ${category} package failed: ${package}" >&2
    fi
    mkdir -p "${records_dir}/optional-installs.d"
    printf '{"category": %s, "package": %s, "status": %s}\n' "$(json_string "${category}")" "$(json_string "${package}")" "$(json_string "${status}")" >> "${records_dir}/optional-installs.d/${step_slug}.jsonl"
}

json_string() {
    local value="${1//\\/\\\\}"
    value="${value//\"/\\\"}"
    printf '"%s"' "${value}"
}

log_refresh() {
    echo "Installing the latest packages (refresh ${1:-none})"
}

remove_bytecode() {
    local directory="$1"
    find "${directory}" -name '__pycache__' -type d -prune -exec rm -rf {} +
}

require_files() {
    local path
    for path in "$@"; do
        if [[ -z "${path}" || ! -e "${path}" ]]; then
            echo "Missing ${path:-an expected file} after ${step_name}" >&2
            return 1
        fi
    done
}

require_libraries() {
    local path
    local missing_libraries
    for path in "$@"; do
        missing_libraries="$(ldd "${path}" 2>/dev/null | grep 'not found' || true)"
        if [[ -n "${missing_libraries}" ]]; then
            echo "Missing shared libraries for ${path}:" >&2
            echo "${missing_libraries}" >&2
            return 1
        fi
    done
}