#!/usr/bin/env bash

install_step() {
    download "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-$(by_architecture x86_64 aarch64)-unknown-linux-musl.tar.gz" /tmp/uv.tgz
    tar -xzf /tmp/uv.tgz -C /usr/local/bin --strip-components=1

    uv venv --seed --python /usr/bin/python3 /opt/pytools
    uv pip install --python /opt/pytools/bin/python --upgrade pip setuptools wheel
    remove_bytecode /opt/pytools

    uv --version
    /opt/pytools/bin/python --version
}