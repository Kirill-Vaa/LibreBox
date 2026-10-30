#!/usr/bin/env bash

install_cewl() {
    clone_repository https://github.com/digininja/CeWL.git /opt/cewl
    gem install --no-document getoptlong mime mime-types mini_exiftool nokogiri public_suffix rexml rubyzip spider
    chmod 0755 /opt/cewl/cewl.rb
    ln -sf /opt/cewl/cewl.rb /usr/local/bin/cewl

    cewl --help >/dev/null
}

install_exploitdb() {
    clone_repository https://gitlab.com/exploit-database/exploitdb.git /opt/exploitdb
    ln -sf /opt/exploitdb/searchsploit /usr/local/bin/searchsploit
}

install_recon_ng() {
    clone_repository https://github.com/lanmaster53/recon-ng.git /opt/recon-ng
    uv venv --python /usr/bin/python3 /opt/recon-ng/venv
    uv pip install --python /opt/recon-ng/venv/bin/python -r /opt/recon-ng/REQUIREMENTS
    printf '%s\n' '#!/usr/bin/env bash' 'exec /opt/recon-ng/venv/bin/python /opt/recon-ng/recon-ng "$@"' > /usr/local/bin/recon-ng
    chmod 0755 /usr/local/bin/recon-ng

    recon-ng --version
}

install_whatweb() {
    clone_repository https://github.com/urbanadventurer/WhatWeb.git /opt/whatweb "v${WHATWEB_VERSION}"
    rm -rf /opt/whatweb/test
    gem install --no-document addressable ipaddr json
    ln -sf /opt/whatweb/whatweb /usr/local/bin/whatweb

    whatweb --version
}

install_wordlists() {
    clone_repository https://github.com/fuzzdb-project/fuzzdb.git /usr/share/fuzzdb
    clone_repository https://github.com/swisskyrepo/PayloadsAllTheThings.git /usr/share/payloads
    export_path /usr/share/fuzzdb /usr/share/payloads
}

install_step() {
    log_refresh "${PACKAGES_REFRESH}"

    install_optional git cewl install_cewl
    install_optional git exploitdb install_exploitdb
    install_optional git recon-ng install_recon_ng
    install_optional git whatweb install_whatweb
    install_wordlists
}