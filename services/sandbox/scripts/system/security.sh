#!/usr/bin/env bash

install_step() {
    apt_install \
        arp-scan arping bettercap bind9-dnsutils binwalk crunch dnsenum ethtool ettercap-text-only \
        fcrackzip fierce foremost fping gdb gobuster hashcat hashid hexedit hping3 hydra iproute2 \
        iptables john libpcap-dev ltrace masscan medusa mtr-tiny ncat ncrack net-tools netcat-openbsd \
        nftables ngrep nikto nmap openssl pdfcrack proxychains4 radare2 rlwrap samba-common-bin \
        scalpel sleuthkit smbclient socat sqlmap ssdeep steghide stegseek tcpdump termshark tor \
        torsocks tshark upx-ucl wafw00f whois xxd

    require_commands bettercap binwalk dig gdb gobuster hashcat hydra john masscan ncat nikto nmap radare2 sqlmap tshark
}