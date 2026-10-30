#!/usr/bin/env bash

install_step() {
    local architecture
    architecture="$(dpkg --print-architecture)"

    download "https://github.com/TomWright/dasel/releases/download/v${DASEL_VERSION}/dasel_linux_${architecture}" /usr/local/bin/dasel
    chmod 0755 /usr/local/bin/dasel

    download "https://github.com/muesli/duf/releases/download/v${DUF_VERSION}/duf_${DUF_VERSION}_linux_$(by_architecture x86_64 arm64).tar.gz" /tmp/duf.tgz
    tar -xzf /tmp/duf.tgz -C /usr/local/bin duf

    download "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_${architecture}" /usr/local/bin/shfmt
    chmod 0755 /usr/local/bin/shfmt

    download "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_${architecture}" /usr/local/bin/yq
    chmod 0755 /usr/local/bin/yq

    dasel version
    duf --version
    shfmt --version
    yq --version
}