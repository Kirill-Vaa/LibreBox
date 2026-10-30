#!/usr/bin/env bash

install_step() {
    local architecture
    architecture="$(dpkg --print-architecture)"

    mkdir -p /opt/tools
    download "https://github.com/iBotPeaches/Apktool/releases/download/v${APKTOOL_VERSION}/apktool_${APKTOOL_VERSION}.jar" /opt/tools/apktool.jar
    printf '%s\n' '#!/usr/bin/env bash' 'exec java -jar /opt/tools/apktool.jar "$@"' > /usr/local/bin/apktool
    chmod 0755 /usr/local/bin/apktool

    download "https://github.com/jpillora/chisel/releases/download/v${CHISEL_VERSION}/chisel_${CHISEL_VERSION}_linux_${architecture}.gz" /tmp/chisel.gz
    gunzip /tmp/chisel.gz
    install -m 0755 /tmp/chisel /usr/local/bin/chisel

    download "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_$(by_architecture x64 arm64).tar.gz" /tmp/gitleaks.tgz
    tar -xzf /tmp/gitleaks.tgz -C /usr/local/bin gitleaks

    download "https://github.com/anchore/grype/releases/download/v${GRYPE_VERSION}/grype_${GRYPE_VERSION}_linux_${architecture}.tar.gz" /tmp/grype.tgz
    tar -xzf /tmp/grype.tgz -C /usr/local/bin grype

    download "https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip" /tmp/jadx.zip
    mkdir -p /opt/jadx
    unzip -q /tmp/jadx.zip -d /opt/jadx
    ln -sf /opt/jadx/bin/jadx /usr/local/bin/jadx

    download "https://github.com/nicocha30/ligolo-ng/releases/download/v${LIGOLO_NG_VERSION}/ligolo-ng_agent_${LIGOLO_NG_VERSION}_linux_${architecture}.tar.gz" /tmp/ligolo.tgz
    tar -xzf /tmp/ligolo.tgz -C /tmp agent
    install -m 0755 /tmp/agent /usr/local/bin/ligolo-agent

    download "https://github.com/BishopFox/sliver/releases/download/v${SLIVER_VERSION}/sliver-client_linux-${architecture}" /usr/local/bin/sliver-client
    download "https://github.com/BishopFox/sliver/releases/download/v${SLIVER_VERSION}/sliver-server_linux-${architecture}" /usr/local/bin/sliver-server
    chmod 0755 /usr/local/bin/sliver-client /usr/local/bin/sliver-server

    download "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_linux_${architecture}.tar.gz" /tmp/syft.tgz
    tar -xzf /tmp/syft.tgz -C /usr/local/bin syft

    download "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-$(by_architecture 64bit ARM64).tar.gz" /tmp/trivy.tgz
    tar -xzf /tmp/trivy.tgz -C /usr/local/bin trivy

    require_libraries /usr/local/bin/chisel /usr/local/bin/sliver-client /usr/local/bin/trivy
    chisel --version
    gitleaks version
    grype version
    sliver-client version
    syft version
    trivy --version
}