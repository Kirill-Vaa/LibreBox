#!/usr/bin/env bash
set -euo pipefail

profile="$1"
records_dir=/usr/local/share/libre-box
removed_files_dir="${records_dir}/removed-files.d"

if [[ -d "${removed_files_dir}" ]]; then
    removed_count=0
    while IFS= read -r -d '' path; do
        if [[ -f "/${path}" || -L "/${path}" ]]; then
            rm -f "/${path}"
            removed_count=$((removed_count + 1))
        fi
    done < <(cat "${removed_files_dir}"/*)
    rm -rf "${removed_files_dir}"
    echo "Removed ${removed_count} files that later build steps replaced"
fi

rm -f /etc/apt/apt.conf.d/90-libre-box-build
cat > /etc/apt/apt.conf.d/docker-clean <<'APT_CONFIG'
DPkg::Post-Invoke { "rm -f /var/cache/apt/archives/*.deb /var/cache/apt/archives/partial/*.deb /var/cache/apt/*.bin || true"; };
APT::Update::Post-Invoke { "rm -f /var/cache/apt/archives/*.deb /var/cache/apt/archives/partial/*.deb /var/cache/apt/*.bin || true"; };
Dir::Cache::pkgcache ""; Dir::Cache::srcpkgcache "";
APT_CONFIG

for tools_dir in /opt/pipx /opt/pytools; do
    if [[ -d "${tools_dir}" ]]; then
        find "${tools_dir}" -name '__pycache__' -type d -prune -exec rm -rf {} +
    fi
done

python3 /build/inventory.py --profile "${profile}"