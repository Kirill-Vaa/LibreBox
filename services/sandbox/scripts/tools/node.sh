#!/usr/bin/env bash

install_step() {
    download "https://github.com/Schniz/fnm/releases/download/v${FNM_VERSION}/$(by_architecture fnm-linux fnm-arm64).zip" /tmp/fnm.zip
    unzip -q -o /tmp/fnm.zip -d /usr/local/bin
    chmod 0755 /usr/local/bin/fnm

    fnm install "${NODE_VERSION}"
    fnm default "${NODE_VERSION}"
    ln -sfn "${FNM_DIR}/node-versions/v${NODE_VERSION}/installation" /opt/node

    /opt/node/bin/npm install -g --allow-scripts=pnpm,yarn pnpm yarn
    /opt/node/bin/npm install -g "@playwright/cli@${PLAYWRIGHT_CLI_VERSION}"

    /opt/node/bin/node --version
    /opt/node/bin/pnpm --version
    /opt/node/bin/yarn --version
    /opt/node/bin/playwright-cli --version
}