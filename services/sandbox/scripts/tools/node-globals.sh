#!/usr/bin/env bash

install_step() {
    log_refresh "${PACKAGES_REFRESH}"

    /opt/node/bin/npm install -g \
        @marp-team/marp-cli @mermaid-js/mermaid-cli decktape eslint prettier repomix ts-node typescript

    require_commands marp mmdc decktape eslint prettier repomix ts-node tsc
}