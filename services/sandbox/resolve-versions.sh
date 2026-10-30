#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit

pins_path="$1"
target_architecture="${TARGETARCH:-$(dpkg --print-architecture)}"

resolved_names=(
    DOTNET_CHANNEL JAVA_VERSION NODE_MAJOR_VERSION
    AGE_VERSION APKTOOL_VERSION AWSCLI_VERSION BUN_VERSION CARGO_BINSTALL_VERSION CHISEL_VERSION CHROME_VERSION COMPOSE_VERSION
    D2_VERSION DASEL_VERSION DENO_VERSION DOCKER_VERSION DOTNET_SDK_VERSION DUF_VERSION FNM_VERSION GHIDRA_VERSION GHIDRA_DATE
    GITLEAKS_VERSION GO_VERSION GRADLE_VERSION GRYPE_VERSION HELM_VERSION JADX_VERSION JULIA_VERSION K9S_VERSION KUBECTL_VERSION
    KUSTOMIZE_VERSION LIGOLO_NG_VERSION METASPLOIT_VERSION MONGODB_TOOLS_VERSION MONGOSH_VERSION NODE_VERSION PACKER_VERSION
    PLAYWRIGHT_CLI_VERSION POWERSHELL_VERSION PYENV_RELEASE RBENV_RELEASE RUBY_BUILD_RELEASE RUST_VERSION SECLISTS_VERSION
    SHFMT_VERSION SLIVER_VERSION SOPS_VERSION SYFT_VERSION TERRAFORM_VERSION TOFU_VERSION TRIVY_VERSION TYPST_VERSION
    USQL_VERSION UV_VERSION VAULT_VERSION WHATWEB_VERSION YQ_VERSION
)

apt_index_version() {
    local index_url="$1"
    local package="$2"
    local index
    index="$(fetch "${index_url}")"
    awk -v package="${package}" '/^Package: / {name = $2} name == package && /^Version: / {print $2}' <<< "${index}" | sort -V | tail -n 1
}

fetch() {
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time 180 "$@"
}

git_latest_tag() {
    local repository="$1"
    local prefix="$2"
    local tags
    tags="$(git ls-remote --tags --refs "https://github.com/${repository}" "refs/tags/${prefix}*")"
    sed -E "s#^.*refs/tags/${prefix}##" <<< "${tags}" | grep -E '^[0-9]+(\.[0-9]+)+$' | sort -V | tail -n 1
}

github_tag() {
    local repository="$1"
    local url
    url="$(fetch -I -o /dev/null -w '%{url_effective}' "https://github.com/${repository}/releases/latest")"
    case "${url}" in
        */releases/tag/*) echo "${url##*/releases/tag/}" ;;
        *)
            echo "https://github.com/${repository}/releases/latest did not redirect to a release" >&2
            return 1
            ;;
    esac
}

github_version() {
    local repository="$1"
    local tag_prefix="${2:-v}"
    local tag
    tag="$(github_tag "${repository}")"
    echo "${tag#"${tag_prefix}"}"
}

hashicorp_version() {
    local product="$1"
    fetch "https://checkpoint-api.hashicorp.com/v1/check/${product}" | jq -r .current_version
}

resolve() {
    local body
    case "$1" in
        DOTNET_CHANNEL) fetch https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json | jq -r '[.["releases-index"][] | select(.["release-type"] == "lts" and .["support-phase"] == "active")] | max_by(.["channel-version"] | split(".") | map(tonumber)) | .["channel-version"]' ;;
        JAVA_VERSION)
            apt-get update -qq >/dev/null
            apt-cache depends default-jdk | sed -n -E 's/^ *Depends: openjdk-([0-9]+)-jdk$/\1/p' | head -n 1
            ;;
        NODE_MAJOR_VERSION) fetch https://nodejs.org/dist/index.json | jq -r '[.[] | select(.lts != false)][0].version | ltrimstr("v") | split(".")[0]' ;;
        AGE_VERSION) github_version FiloSottile/age ;;
        APKTOOL_VERSION) github_version iBotPeaches/Apktool ;;
        AWSCLI_VERSION) git_latest_tag aws/aws-cli 2. | sed 's/^/2./' ;;
        BUN_VERSION) github_version oven-sh/bun bun-v ;;
        CARGO_BINSTALL_VERSION) github_version cargo-bins/cargo-binstall ;;
        CHISEL_VERSION) github_version jpillora/chisel ;;
        CHROME_VERSION) apt_index_version "https://dl.google.com/linux/chrome/deb/dists/stable/main/binary-${target_architecture}/Packages" google-chrome-stable ;;
        COMPOSE_VERSION) github_version docker/compose ;;
        D2_VERSION) github_version terrastruct/d2 ;;
        DASEL_VERSION) github_version TomWright/dasel ;;
        DENO_VERSION) github_version denoland/deno ;;
        DOCKER_VERSION)
            local machine=x86_64
            if [[ "${target_architecture}" == arm64 ]]; then
                machine=aarch64
            fi
            body="$(fetch "https://download.docker.com/linux/static/stable/${machine}/")"
            grep -o -E 'docker-[0-9]+\.[0-9]+\.[0-9]+\.tgz' <<< "${body}" | sed -E 's/^docker-//; s/\.tgz$//' | sort -V | tail -n 1
            ;;
        DOTNET_SDK_VERSION) fetch "https://builds.dotnet.microsoft.com/dotnet/release-metadata/${DOTNET_CHANNEL}/releases.json" | jq -r '."latest-sdk"' ;;
        DUF_VERSION) github_version muesli/duf ;;
        FNM_VERSION) github_version Schniz/fnm ;;
        GHIDRA_VERSION)
            body="$(github_tag NationalSecurityAgency/ghidra)"
            body="${body#Ghidra_}"
            echo "${body%_build}"
            ;;
        GHIDRA_DATE)
            body="$(fetch "https://github.com/NationalSecurityAgency/ghidra/releases/expanded_assets/Ghidra_${GHIDRA_VERSION}_build")"
            grep -o -E "ghidra_${GHIDRA_VERSION//./\\.}_PUBLIC_[0-9]{8}\.zip" <<< "${body}" | sed -n -E '1s/^.*_PUBLIC_([0-9]{8})\.zip$/\1/p'
            ;;
        GITLEAKS_VERSION) github_version gitleaks/gitleaks ;;
        GO_VERSION) fetch 'https://go.dev/dl/?mode=json' | jq -r '[.[] | select(.stable)][0].version | ltrimstr("go")' ;;
        GRADLE_VERSION) fetch https://services.gradle.org/versions/current | jq -r .version ;;
        GRYPE_VERSION) github_version anchore/grype ;;
        HELM_VERSION) github_version helm/helm ;;
        JADX_VERSION) github_version skylot/jadx ;;
        JULIA_VERSION) fetch https://julialang-s3.julialang.org/bin/versions.json | jq -r '[to_entries[] | select(.value.stable) | .key] | max_by(split(".") | map(tonumber))' ;;
        K9S_VERSION) github_version derailed/k9s ;;
        KUBECTL_VERSION) fetch https://dl.k8s.io/release/stable.txt | sed 's/^v//' ;;
        KUSTOMIZE_VERSION) git_latest_tag kubernetes-sigs/kustomize kustomize/v ;;
        LIGOLO_NG_VERSION) github_version nicocha30/ligolo-ng ;;
        METASPLOIT_VERSION)
            body="$(apt_index_version "https://downloads.metasploit.com/data/releases/metasploit-framework/apt/dists/lucid/main/binary-${target_architecture}/Packages" metasploit-framework)"
            echo "${body%%~*}"
            ;;
        MONGODB_TOOLS_VERSION) fetch https://downloads.mongodb.org/tools/db/release.json | jq -r '.versions[0].version' ;;
        MONGOSH_VERSION) github_version mongodb-js/mongosh ;;
        NODE_VERSION) fetch https://nodejs.org/dist/index.json | jq -r --arg prefix "v${NODE_MAJOR_VERSION}." '[.[] | select(.version | startswith($prefix))][0].version | ltrimstr("v")' ;;
        PACKER_VERSION) hashicorp_version packer ;;
        PLAYWRIGHT_CLI_VERSION) fetch 'https://registry.npmjs.org/@playwright%2fcli/latest' | jq -r .version ;;
        POWERSHELL_VERSION) github_version PowerShell/PowerShell ;;
        PYENV_RELEASE) github_version pyenv/pyenv ;;
        RBENV_RELEASE) github_version rbenv/rbenv ;;
        RUBY_BUILD_RELEASE) github_version rbenv/ruby-build ;;
        RUST_VERSION)
            body="$(fetch https://static.rust-lang.org/dist/channel-rust-stable.toml)"
            awk '/^\[pkg\.rust\]$/ {section = 1; next} /^\[/ {section = 0} section && $1 == "version" {gsub(/"/, "", $3); print $3}' <<< "${body}"
            ;;
        SECLISTS_VERSION) github_version danielmiessler/SecLists ;;
        SHFMT_VERSION) github_version mvdan/sh ;;
        SLIVER_VERSION) github_version BishopFox/sliver ;;
        SOPS_VERSION) github_version getsops/sops ;;
        SYFT_VERSION) github_version anchore/syft ;;
        TERRAFORM_VERSION) hashicorp_version terraform ;;
        TOFU_VERSION) github_version opentofu/opentofu ;;
        TRIVY_VERSION) github_version aquasecurity/trivy ;;
        TYPST_VERSION) github_version typst/typst ;;
        USQL_VERSION) github_version xo/usql ;;
        UV_VERSION) github_version astral-sh/uv ;;
        VAULT_VERSION) hashicorp_version vault ;;
        WHATWEB_VERSION) github_version urbanadventurer/WhatWeb ;;
        YQ_VERSION) github_version mikefarah/yq ;;
        *)
            echo "resolve-versions.sh has no rule for $1" >&2
            return 1
            ;;
    esac
}

pinned_names=()
while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    if [[ "${line}" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]]; then
        pinned_names+=("${BASH_REMATCH[1]}")
        printf -v "${BASH_REMATCH[1]}" '%s' "${BASH_REMATCH[2]}"
    fi
done < "${pins_path}"

current_name=""
trap 'echo "Failed to resolve ${current_name}. The build looks up the latest releases online, so check the network, or pin ${current_name} in config/versions.env" >&2' ERR

for name in "${resolved_names[@]}"; do
    current_name="${name}"
    if [[ -n "${!name:-}" ]]; then
        printf '%-24s %s (pinned)\n' "${name}" "${!name}" >&2
        continue
    fi

    value="$(resolve "${name}")"
    if [[ ! "${value}" =~ ^[0-9][0-9A-Za-z.+~:_-]*$ ]]; then
        echo "Resolved an invalid value for ${name}: '${value}'" >&2
        false
    fi

    printf -v "${name}" '%s' "${value}"
    printf '%-24s %s\n' "${name}" "${value}" >&2
done

for name in "${pinned_names[@]}" "${resolved_names[@]}"; do
    printf '%s=%s\n' "${name}" "${!name}"
done | LC_ALL=C sort -u