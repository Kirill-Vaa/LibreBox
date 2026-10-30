#!/usr/bin/env bash

install_step() {
    log_refresh "${PACKAGES_REFRESH}"

    pipx install poetry

    local tool
    for tool in ansible-lint csvkit files-to-prompt llm ocrmypdf ttok visidata weasyprint yamllint yt-dlp; do
        install_optional pipx "${tool}" pipx install "${tool}"
    done

    install_optional pipx ansible pipx install --include-deps ansible

    rm -rf /opt/pipx/logs /opt/pipx/.cache
    remove_bytecode /opt/pipx
}