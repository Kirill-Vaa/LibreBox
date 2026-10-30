#!/usr/bin/env bash

install_step() {
    local tools_name
    tools_name="mongodb-database-tools-ubuntu2604-$(by_architecture x86_64 arm64)-${MONGODB_TOOLS_VERSION}"
    download "https://fastdl.mongodb.org/tools/db/${tools_name}.tgz" /tmp/mongodb-tools.tgz
    tar -xzf /tmp/mongodb-tools.tgz -C /usr/local/bin --strip-components=2 "${tools_name}/bin/*"

    download "https://github.com/mongodb-js/mongosh/releases/download/v${MONGOSH_VERSION}/mongosh-${MONGOSH_VERSION}-linux-$(by_architecture x64 arm64).tgz" /tmp/mongosh.tgz
    tar -xzf /tmp/mongosh.tgz -C /usr/local/bin --strip-components=2 "mongosh-${MONGOSH_VERSION}-linux-*/bin/*"

    download "https://github.com/xo/usql/releases/download/v${USQL_VERSION}/usql_static-${USQL_VERSION}-linux-$(dpkg --print-architecture).tar.bz2" /tmp/usql.tbz2
    tar -xjf /tmp/usql.tbz2 -C /tmp usql_static
    install -m 0755 /tmp/usql_static /usr/local/bin/usql

    mongodump --version
    mongosh --version
    usql --version
}