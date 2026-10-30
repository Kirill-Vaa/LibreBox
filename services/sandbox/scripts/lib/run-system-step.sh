#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit

step_name="$(cat /build/name)"
step_slug="${step_name//\//-}"

source /build/lib/system-helpers.sh
source /build/versions.env
source /build/step.sh

ensure_locale

cd /tmp

is_security_step=false
if [[ "${step_name}" == system/security ]]; then
    is_security_step=true
    list_commands > /tmp/commands-before
fi

echo "Running ${step_name}"
install_step

if [[ "${is_security_step}" == true ]]; then
    mkdir -p "${records_dir}/security-commands.d"
    list_commands | LC_ALL=C comm -13 /tmp/commands-before - > "${records_dir}/security-commands.d/${step_slug}.txt"
fi