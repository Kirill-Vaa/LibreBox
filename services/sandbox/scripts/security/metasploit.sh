#!/usr/bin/env bash

install_metasploit() {
    local architecture
    architecture="$(dpkg --print-architecture)"
    local repository_url=https://downloads.metasploit.com/data/releases/metasploit-framework/apt

    local package_path
    package_path="$(fetch "${repository_url}/dists/lucid/main/binary-${architecture}/Packages" | awk -v version="${METASPLOIT_VERSION}" '
        /^Package: / {name = $2}
        /^Version: / {package_version = $2}
        /^Filename: / && name == "metasploit-framework" && index(package_version, version "~") == 1 {path = $2}
        END {print path}
    ')"
    if [[ -z "${package_path}" ]]; then
        echo "Rapid7's repository has no metasploit-framework ${METASPLOIT_VERSION} for ${architecture}" >&2
        return 1
    fi

    download "${repository_url}/${package_path}" /tmp/metasploit.deb
    mkdir -p /tmp/metasploit
    dpkg-deb --fsys-tarfile /tmp/metasploit.deb | tar -xf - -C /tmp/metasploit
    mv /tmp/metasploit/opt/metasploit-framework /opt/metasploit-framework

    local name
    for name in msfconsole msfd msfdb msfrpc msfrpcd msfupdate msfvenom; do
        if [[ -e "/opt/metasploit-framework/bin/${name}" ]]; then
            ln -sf "/opt/metasploit-framework/bin/${name}" "/usr/local/bin/${name}"
        fi
    done

    /opt/metasploit-framework/bin/msfvenom --list formats >/dev/null
}

install_step() {
    install_optional metasploit metasploit-framework install_metasploit
}