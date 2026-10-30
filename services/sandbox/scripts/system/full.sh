#!/usr/bin/env bash

install_step() {
    apt-get update

    local icu_package
    icu_package="$(apt-cache search --names-only '^libicu[0-9]+$' | cut -d ' ' -f 1 | sort -V | tail -n 1)"

    local -a texlive_packages
    mapfile -t texlive_packages < <(apt-cache depends texlive-full | sed -n -E 's/^ *\|?Depends: ([^<>]+)$/\1/p' | grep -v -- '-doc$')

    apt_install \
        libgmp-dev libreoffice libyaml-dev lua5.4 luarocks perl php-cli php-curl \
        php-mbstring r-base ruby-full "${icu_package}" "${texlive_packages[@]}"

    require_commands biber gem libreoffice lua5.4 lualatex luarocks pdflatex perl php Rscript ruby xelatex
}