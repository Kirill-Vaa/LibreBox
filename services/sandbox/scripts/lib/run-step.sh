#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit

step_name="$(cat /build/name)"
step_slug="${step_name//\//-}"
export_roots=(opt usr/local)
cache_paths=(opt/cargo/git opt/cargo/registry opt/gopath/pkg opt/state)

source /build/lib/install-helpers.sh
source /build/versions.env
source /build/step.sh

ensure_locale

export GOFLAGS=-modcacherw
export GOTOOLCHAIN=local
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_ROOT_USER_ACTION=ignore
export PYTHONDONTWRITEBYTECODE=1
export UV_LINK_MODE=copy
export npm_config_audit=false
export npm_config_cache="${XDG_CACHE_HOME}/npm"
export npm_config_fund=false
export npm_config_update_notifier=false

mkdir -p /tmp/build-bin
printf '#!/bin/sh\nexec /usr/bin/bsdtar "$@"\n' > /tmp/build-bin/tar
chmod 0755 /tmp/build-bin/tar
export PATH="/tmp/build-bin:${PATH}"

list_installed_files() {
    local cache_path
    local -a prune_arguments=()
    for cache_path in "${cache_paths[@]}"; do
        prune_arguments+=(-path "${cache_path}" -o)
    done
    unset 'prune_arguments[-1]'
    find "${export_roots[@]}" -xdev \( "${prune_arguments[@]}" \) -prune -o "$@" -print0
}

cd /tmp

is_security_step=false
if [[ "${step_name}" == security/* ]]; then
    is_security_step=true
    list_commands > /tmp/commands-before
fi

(cd / && list_installed_files \( -type f -o -type l \) -not -name '*.pyc') | LC_ALL=C sort -z > /tmp/files-before

touch /tmp/step-marker
sleep 1
echo "Running ${step_name}"
install_step

if [[ "${is_security_step}" == true ]]; then
    mkdir -p "${records_dir}/security-commands.d"
    list_commands | LC_ALL=C comm -13 /tmp/commands-before - > "${records_dir}/security-commands.d/${step_slug}.txt"
fi

cd /
list_installed_files \( -type f -o -type l \) -not -name '*.pyc' | LC_ALL=C sort -z > /tmp/files-after
LC_ALL=C comm -z -23 /tmp/files-before /tmp/files-after > /tmp/files-removed
{
    list_installed_files -cnewer /tmp/step-marker \( -type f -o -type l -o \( -type d -empty \) \)
    for path in "${exported_paths[@]}"; do
        if [[ ! -e "${path}" && ! -L "${path}" ]]; then
            echo "${step_name} exports ${path}, which does not exist" >&2
            exit 1
        fi
        find "${path#/}" \( -type f -o -type l -o \( -type d -empty \) \) -print0
    done
} | LC_ALL=C sort -z -u > /tmp/step-outputs

if [[ ! -s /tmp/step-outputs ]]; then
    echo "${step_name} installed nothing under /opt or /usr/local" >&2
    exit 1
fi

rm -rf /out
mkdir -p /out
tar --null --no-recursion -T /tmp/step-outputs -cf - | tar -C /out -xpf -
xargs -0 rm -f -d -- < /tmp/step-outputs

if [[ -s /tmp/files-removed ]]; then
    mkdir -p "/out${records_dir}/removed-files.d"
    cp /tmp/files-removed "/out${records_dir}/removed-files.d/${step_slug}"
    echo "${step_name} removed $(tr -cd '\0' < /tmp/files-removed | wc -c) files installed by earlier steps"
fi
echo "Exported $(tr -cd '\0' < /tmp/step-outputs | wc -c) paths from ${step_name}"