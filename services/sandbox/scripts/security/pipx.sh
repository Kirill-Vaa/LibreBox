#!/usr/bin/env bash

legacy_python=""

install_checked() {
    local command_name="$1"
    shift
    pipx install "$@"
    "${command_name}" --help >/dev/null
}

install_legacy() {
    pipx install --python "${legacy_python}" "$@"
}

install_patator() {
    echo "setuptools<81" > /tmp/build-constraints.txt
    pipx install --pip-args="--build-constraint /tmp/build-constraints.txt" patator
    local version_output
    version_output="$(patator --version 2>&1 || true)"
    [[ "${version_output}" == Patator\ * ]]
}

install_wfuzz() {
    install_legacy git+https://github.com/xmendez/wfuzz
    pipx inject wfuzz "setuptools<81"
    wfuzz --version
}

install_step() {
    log_refresh "${PACKAGES_REFRESH}"
    export UV_PYTHON_INSTALL_DIR=/opt/uv/python

    local tool
    for tool in \
        arjun bloodhound certipy-ad checkov coercer dirsearch frida-tools holehe impacket \
        ldapdomaindump lsassy maigret name-that-hash pypykatz scoutsuite sherlock-project \
        smbmap sublist3r volatility3; do
        install_optional pipx "${tool}" pipx install "${tool}"
    done

    if [[ -d /opt/pipx/venvs/impacket ]]; then
        install_optional pipx impacket-extras pipx inject impacket pcapy-ng pyasyncore
        local script
        for script in /opt/pipx/venvs/impacket/bin/*.py; do
            ln -sf "${script}" "/opt/pipx/bin/impacket-$(basename "${script}" .py)"
        done
    fi

    install_optional pipx commix install_checked commix git+https://github.com/commixproject/commix
    install_optional pipx dnsrecon install_checked dnsrecon git+https://github.com/darkoperator/dnsrecon
    install_optional pipx enum4linux-ng install_checked enum4linux-ng git+https://github.com/cddmp/enum4linux-ng
    install_optional pipx netexec install_checked nxc git+https://github.com/Pennyw0rth/NetExec
    install_optional pipx patator install_patator
    install_optional pipx responder install_checked responder git+https://github.com/lgandx/Responder
    install_optional pipx theHarvester install_checked theHarvester git+https://github.com/laramies/theHarvester

    uv python install --no-bin 3.11
    legacy_python="$(uv python find 3.11)"
    install_optional pipx droopescan install_legacy droopescan
    install_optional pipx prowler install_legacy prowler
    install_optional pipx wfuzz install_wfuzz

    rm -rf /opt/pipx/logs /opt/pipx/.cache
    remove_bytecode /opt/pipx
}