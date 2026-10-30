#!/usr/bin/env bash

install_step() {
    log_refresh "${PACKAGES_REFRESH}"

    local crate
    for crate in feroxbuster rustscan; do
        install_optional cargo "${crate}" install_crate "${crate}"
    done
}