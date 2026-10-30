#!/usr/bin/env bash

install_step() {
    download "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/ghidra_${GHIDRA_VERSION}_PUBLIC_${GHIDRA_DATE}.zip" /tmp/ghidra.zip
    unzip -q /tmp/ghidra.zip -d /tmp
    mv "/tmp/ghidra_${GHIDRA_VERSION}_PUBLIC" /opt/ghidra

    if [[ "$(dpkg --print-architecture)" != amd64 ]]; then
        GRADLE_USER_HOME=/tmp/gradle-home /opt/gradle/bin/gradle --no-daemon --quiet --project-dir /opt/ghidra/support/gradle buildNatives
        rm -rf /opt/ghidra/support/gradle/.gradle /opt/ghidra/support/gradle/build
    fi

    ln -sf /opt/ghidra/ghidraRun /usr/local/bin/ghidra
    ln -sf /opt/ghidra/support/analyzeHeadless /usr/local/bin/ghidra-analyze-headless

    require_files "$(find /opt/ghidra/Ghidra/Features/Decompiler -path "*/os/linux_$(by_architecture x86_64 arm_64)/decompile" -print -quit)"
}