#!/usr/bin/env bash

install_step() {
    log_refresh "${PACKAGES_REFRESH}"

    local gem
    for gem in evil-winrm wpscan zsteg; do
        install_optional gem "${gem}" gem install --no-document "${gem}"
    done
}