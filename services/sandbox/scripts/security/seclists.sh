#!/usr/bin/env bash

install_step() {
    clone_repository https://github.com/danielmiessler/SecLists.git /usr/share/seclists "${SECLISTS_VERSION}"

    mkdir -p /usr/share/wordlists
    tar -xzf /usr/share/seclists/Passwords/Leaked-Databases/rockyou.txt.tar.gz --no-same-owner -C /usr/share/wordlists rockyou.txt
    chmod 0644 /usr/share/wordlists/rockyou.txt
    ln -sf /usr/share/nmap/nselib/data/passwords.lst /usr/share/wordlists/nmap.lst
    ln -sfn /usr/share/seclists /usr/share/wordlists/seclists

    require_files /usr/share/nmap/nselib/data/passwords.lst /usr/share/seclists/Discovery/Web-Content /usr/share/wordlists/rockyou.txt
    export_path /usr/share/seclists /usr/share/wordlists
}