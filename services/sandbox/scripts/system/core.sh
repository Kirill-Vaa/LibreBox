#!/usr/bin/env bash

install_step() {
    apt_install \
        aria2 bash-completion bat btop build-essential bzip2 ca-certificates cmake curl direnv entr eza \
        fd-find file fish fontconfig fonts-dejavu fonts-liberation fonts-liberation2 fonts-noto-cjk \
        fonts-noto-color-emoji fonts-noto-core fzf g++ gcc git git-delta git-lfs gnupg htop httpie jq \
        less libarchive-tools libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
        libcairo2 libcups2t64 libcurl4t64 libdbus-1-3 libexpat1 libgbm1 libglib2.0-0t64 libgtk-3-0t64 \
        libnspr4 libnss3 libpango-1.0-0 libudev1 libvulkan1 libx11-6 libxcb1 libxcomposite1 libxdamage1 \
        libxext6 libxfixes3 libxkbcommon0 libxrandr2 locales lsof make moreutils nano ncdu neovim \
        openssh-client parallel pkg-config procps psmisc pv python-is-python3 python3 python3-pip \
        python3-venv ripgrep rsync shellcheck strace tini tmux tree tzdata universal-ctags unzip vim \
        wget x11-utils xdg-utils xvfb xz-utils zip zoxide zsh zstd

    sed -i 's/^# *\(en_US.UTF-8\)/\1/' /etc/locale.gen
    locale-gen en_US.UTF-8

    ln -sf "$(command -v fdfind)" /usr/local/bin/fd
    ln -sf "$(command -v batcat)" /usr/local/bin/bat

    cat > /etc/fonts/conf.d/59-sandbox-zh.conf <<'FONTCONFIG'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
    <match target="pattern">
        <test name="lang" compare="eq">
            <string>zh</string>
        </test>
        <test name="family" qual="any">
            <string>sans-serif</string>
        </test>
        <edit name="family" mode="prepend" binding="strong">
            <string>Noto Sans CJK SC</string>
        </edit>
    </match>
</fontconfig>
FONTCONFIG
    fc-cache -f

    require_commands bat fd python3.14 tini xdpyinfo Xvfb
}