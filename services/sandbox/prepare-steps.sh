#!/usr/bin/env bash
set -euo pipefail

scripts_dir="$1"
versions_path="$2"
steps_dir="$3"
system_lib_files=(run-system-step.sh system-helpers.sh)

used_versions() {
    local script_path="$1"
    awk '
        NR == FNR {
            if (match($0, /^[A-Z][A-Z0-9_]*=/)) {
                definitions[substr($0, 1, RLENGTH - 1)] = $0
            }
            next
        }
        {
            for (name in definitions) {
                if ($0 ~ ("\\$\\{?" name "([^A-Za-z0-9_]|$)")) {
                    used[name] = 1
                }
            }
        }
        END {
            for (name in used) {
                print definitions[name]
            }
        }
    ' "${versions_path}" "${script_path}" | LC_ALL=C sort
}

while IFS= read -r script_path; do
    step_name="${script_path#"${scripts_dir}/"}"
    step_name="${step_name%.sh}"
    step_dir="${steps_dir}/${step_name}"

    mkdir -p "${step_dir}/lib"
    cp "${script_path}" "${step_dir}/step.sh"
    if [[ "${step_name}" == system/* ]]; then
        for file_name in "${system_lib_files[@]}"; do
            cp "${scripts_dir}/lib/${file_name}" "${step_dir}/lib/"
        done
    else
        cp "${scripts_dir}"/lib/*.sh "${step_dir}/lib/"
    fi
    printf '%s' "${step_name}" > "${step_dir}/name"
    used_versions "${script_path}" > "${step_dir}/versions.env"
done < <(find "${scripts_dir}" -name '*.sh' -not -path "${scripts_dir}/lib/*" | LC_ALL=C sort)