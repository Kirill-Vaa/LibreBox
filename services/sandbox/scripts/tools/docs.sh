#!/usr/bin/env bash

install_step() {
    download "https://github.com/terrastruct/d2/releases/download/v${D2_VERSION}/d2-v${D2_VERSION}-linux-$(dpkg --print-architecture).tar.gz" /tmp/d2.tgz
    tar -xzf /tmp/d2.tgz -C /usr/local/bin --strip-components=2 "d2-v${D2_VERSION}/bin/d2"

    local typst_target
    typst_target="$(by_architecture x86_64 aarch64)-unknown-linux-musl"
    download "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${typst_target}.tar.xz" /tmp/typst.txz
    tar -xJf /tmp/typst.txz -C /usr/local/bin --strip-components=1 "typst-${typst_target}/typst"

    d2 --version
    typst --version
}