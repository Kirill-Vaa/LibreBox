#!/usr/bin/env bash

install_step() {
    local machine
    machine="$(by_architecture x86_64 aarch64)"

    download "https://static.rust-lang.org/rustup/dist/${machine}-unknown-linux-gnu/rustup-init" /tmp/rustup-init
    chmod 0755 /tmp/rustup-init
    /tmp/rustup-init -y --no-modify-path --profile minimal --component clippy,rustfmt --default-toolchain "${RUST_VERSION}"

    download "https://github.com/cargo-bins/cargo-binstall/releases/download/v${CARGO_BINSTALL_VERSION}/cargo-binstall-${machine}-unknown-linux-musl.tgz" /tmp/cargo-binstall.tgz
    tar -xzf /tmp/cargo-binstall.tgz -C /opt/cargo/bin cargo-binstall

    /opt/cargo/bin/rustc --version
    /opt/cargo/bin/cargo --version
    /opt/cargo/bin/cargo-binstall -V
}