#!/usr/bin/env bash

install_step() {
    download "https://go.dev/dl/go${GO_VERSION}.linux-$(dpkg --print-architecture).tar.gz" /tmp/go.tgz
    tar -xzf /tmp/go.tgz -C /opt
    mkdir -p /opt/gopath/bin

    /opt/go/bin/go version
}