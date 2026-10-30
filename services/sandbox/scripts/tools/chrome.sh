#!/usr/bin/env bash

install_step() {
    local architecture
    architecture="$(dpkg --print-architecture)"

    local package_path
    package_path="$(fetch "https://dl.google.com/linux/chrome/deb/dists/stable/main/binary-${architecture}/Packages" | awk -v version="${CHROME_VERSION}" '
        /^Package: / {name = $2}
        /^Version: / {package_version = $2}
        /^Filename: / && name == "google-chrome-stable" && package_version == version {print $2; exit}
    ')"
    if [[ -z "${package_path}" ]]; then
        echo "Google's repository has no google-chrome-stable ${CHROME_VERSION} for ${architecture}" >&2
        return 1
    fi

    download "https://dl.google.com/linux/chrome/deb/${package_path}" /tmp/google-chrome.deb
    mkdir -p /tmp/google-chrome
    dpkg-deb --fsys-tarfile /tmp/google-chrome.deb | tar -xf - -C /tmp/google-chrome
    mv /tmp/google-chrome/opt/google /opt/google

    ln -sf /opt/google/chrome/google-chrome /usr/local/bin/google-chrome
    ln -sf /opt/google/chrome/google-chrome /usr/local/bin/google-chrome-stable
    cat > /usr/local/bin/chrome-no-sandbox <<'WRAPPER'
#!/usr/bin/env bash
exec /opt/google/chrome/google-chrome --no-sandbox --disable-dev-shm-usage "$@"
WRAPPER
    chmod 0755 /usr/local/bin/chrome-no-sandbox

    require_libraries /opt/google/chrome/chrome
    /opt/google/chrome/google-chrome --version
}