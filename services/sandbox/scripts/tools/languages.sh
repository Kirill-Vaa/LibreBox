#!/usr/bin/env bash

install_step() {
    download "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-linux-$(by_architecture x64 aarch64).zip" /tmp/bun.zip
    unzip -q -j /tmp/bun.zip -d /usr/local/bin

    download "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-$(by_architecture x86_64 aarch64)-unknown-linux-gnu.zip" /tmp/deno.zip
    unzip -q /tmp/deno.zip -d /usr/local/bin

    download https://dot.net/v1/dotnet-install.sh /tmp/dotnet-install.sh
    bash /tmp/dotnet-install.sh --version "${DOTNET_SDK_VERSION}" --install-dir /opt/dotnet --no-path

    download "https://julialang-s3.julialang.org/bin/linux/$(by_architecture x64 aarch64)/${JULIA_VERSION%.*}/julia-${JULIA_VERSION}-linux-$(by_architecture x86_64 aarch64).tar.gz" /tmp/julia.tgz
    mkdir -p /opt/julia
    tar -xzf /tmp/julia.tgz -C /opt/julia --strip-components=1

    download "https://github.com/PowerShell/PowerShell/releases/download/v${POWERSHELL_VERSION}/powershell-${POWERSHELL_VERSION}-linux-$(by_architecture x64 arm64).tar.gz" /tmp/pwsh.tgz
    mkdir -p /opt/pwsh
    tar -xzf /tmp/pwsh.tgz -C /opt/pwsh
    chmod 0755 /opt/pwsh/pwsh
    ln -sf /opt/pwsh/pwsh /usr/local/bin/pwsh

    clone_repository https://github.com/rbenv/rbenv.git "${RBENV_ROOT}" "v${RBENV_RELEASE}"
    clone_repository https://github.com/rbenv/ruby-build.git "${RBENV_ROOT}/plugins/ruby-build" "v${RUBY_BUILD_RELEASE}"

    bun --version
    deno --version
    /opt/dotnet/dotnet --list-sdks
    /opt/julia/bin/julia --version
    pwsh -NoLogo -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'
    "${RBENV_ROOT}/bin/rbenv" --version
    "${RBENV_ROOT}/plugins/ruby-build/bin/ruby-build" --version
}