#!/usr/bin/env bash

install_go_tool() {
    local module="$1"
    install_optional go "${module}" /opt/go/bin/go install -trimpath -ldflags="-s -w" "${module}"
}

install_step() {
    log_refresh "${PACKAGES_REFRESH}"
    export GOBIN=/opt/gopath/bin

    install_go_tool github.com/ffuf/ffuf/v2@latest
    install_go_tool github.com/hakluke/hakrawler@latest
    install_go_tool github.com/lc/gau/v2/cmd/gau@latest
    install_go_tool github.com/owasp-amass/amass/v5/cmd/amass@latest
    install_go_tool github.com/projectdiscovery/dnsx/cmd/dnsx@latest
    install_go_tool github.com/projectdiscovery/httpx/cmd/httpx@latest
    install_go_tool github.com/projectdiscovery/katana/cmd/katana@latest
    install_go_tool github.com/projectdiscovery/naabu/v2/cmd/naabu@latest
    install_go_tool github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
    install_go_tool github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
    install_go_tool github.com/tomnomnom/assetfinder@latest
    install_go_tool github.com/tomnomnom/waybackurls@latest

    if [[ -f /opt/gopath/bin/httpx ]]; then
        mv /opt/gopath/bin/httpx /opt/gopath/bin/httpx-pd
    fi
}