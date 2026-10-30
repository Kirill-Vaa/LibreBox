# syntax=docker/dockerfile:1

FROM --platform=${BUILDPLATFORM} ubuntu:26.04 AS resolver

RUN --mount=type=cache,id=libre-box-resolver-apt-archives,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=libre-box-resolver-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git jq


FROM resolver AS versions

ARG TARGETARCH

COPY config/versions.env config/versions-refresh* /build-input/config/

RUN --mount=type=bind,source=resolve-versions.sh,target=/build-input/resolve-versions.sh \
    --mount=type=cache,id=libre-box-resolver-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    bash /build-input/resolve-versions.sh /build-input/config/versions.env > /versions.env \
    && printf 'PACKAGES_REFRESH=%s\n' "$(tr -cd '0-9' 2>/dev/null < /build-input/config/versions-refresh)" >> /versions.env


FROM resolver AS steps

RUN --mount=type=bind,from=versions,source=/versions.env,target=/build-input/versions.env \
    --mount=type=bind,source=prepare-steps.sh,target=/build-input/prepare-steps.sh \
    --mount=type=bind,source=scripts,target=/build-input/scripts \
    bash /build-input/prepare-steps.sh /build-input/scripts /build-input/versions.env /steps


FROM ubuntu:26.04 AS base

ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    HISTFILE=/opt/state/bash_history \
    LANG=en_US.UTF-8 \
    TZ=UTC \
    XDG_CACHE_HOME=/opt/state/cache

ENV CARGO_HOME=/opt/cargo \
    DOTNET_ROOT=/opt/dotnet \
    FNM_DIR=/opt/fnm \
    GEM_HOME=/opt/gems \
    GOPATH=/opt/gopath \
    GOROOT=/opt/go \
    NLTK_DATA=/opt/nltk_data \
    PIPX_BIN_DIR=/opt/pipx/bin \
    PIPX_HOME=/opt/pipx \
    PYENV_ROOT=/opt/pyenv \
    RBENV_ROOT=/opt/rbenv \
    RUSTUP_HOME=/opt/rust

ENV CHECKPOINT_DISABLE=1 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    POWERSHELL_TELEMETRY_OPTOUT=1

ENV CHROME_PATH=/usr/local/bin/chrome-no-sandbox \
    DISPLAY=:99 \
    PLAYWRIGHT_MCP_CONFIG=/etc/playwright-cli.config.json \
    PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/chrome-no-sandbox \
    PUPPETEER_SKIP_DOWNLOAD=1

ENV TOOLCHAIN_PATH="/opt/pytools/bin:${PIPX_BIN_DIR}:${PYENV_ROOT}/bin:${RBENV_ROOT}/bin:${GEM_HOME}/bin:${GOROOT}/bin:${GOPATH}/bin:${CARGO_HOME}/bin:/opt/node/bin:${DOTNET_ROOT}:/opt/julia/bin:/root/.local/bin"
ENV PATH="${TOOLCHAIN_PATH}:${PATH}"

RUN mkdir -p /opt/state /root/.box/logs /root/data /usr/local/share/libre-box \
    && printf 'case ":${PATH}:" in\n    *:/opt/pytools/bin:*) ;;\n    *) export PATH="%s:${PATH}" ;;\nesac' "${TOOLCHAIN_PATH}" > /etc/profile.d/10-toolchains.sh \
    && rm -f /etc/apt/apt.conf.d/docker-clean

COPY config/apt-build.conf /etc/apt/apt.conf.d/90-libre-box-build
COPY config/playwright-cli.config.json /etc/playwright-cli.config.json
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

WORKDIR /root/data

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["bash", "-c", "test -f /root/.box/ready && xdpyinfo -display :99 >/dev/null 2>&1"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]


FROM base AS system-core

RUN --mount=type=bind,from=steps,source=/steps/system/core,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-apt-archives-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=libre-box-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    bash /build/lib/run-system-step.sh


FROM system-core AS tool-chrome

RUN --mount=type=bind,from=steps,source=/steps/tools/chrome,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-core AS tool-cli

RUN --mount=type=bind,from=steps,source=/steps/tools/cli,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-core AS tool-node

RUN --mount=type=bind,from=steps,source=/steps/tools/node,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-core AS tool-python

RUN --mount=type=bind,from=steps,source=/steps/tools/python,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-core AS core

COPY --link --from=tool-chrome /out/ /
COPY --link --from=tool-cli /out/ /
COPY --link --from=tool-node /out/ /
COPY --link --from=tool-python /out/ /

RUN --network=none \
    --mount=type=bind,source=finalize-image.sh,target=/build/finalize-image.sh \
    --mount=type=bind,source=inventory.py,target=/build/inventory.py \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/finalize-image.sh core


FROM system-core AS system-standard

RUN --mount=type=bind,from=steps,source=/steps/system/standard,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-apt-archives-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=libre-box-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    bash /build/lib/run-system-step.sh


FROM system-standard AS tool-cloud

RUN --mount=type=bind,from=steps,source=/steps/tools/cloud,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-databases

RUN --mount=type=bind,from=steps,source=/steps/tools/databases,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-docs

RUN --mount=type=bind,from=steps,source=/steps/tools/docs,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-go

RUN --mount=type=bind,from=steps,source=/steps/tools/go,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-java

RUN --mount=type=bind,from=steps,source=/steps/tools/java,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-node-globals

COPY --link --from=tool-node /out/ /

RUN --mount=type=bind,from=steps,source=/steps/tools/node-globals,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-pipx

COPY --link --from=tool-python /out/ /

RUN --mount=type=bind,from=steps,source=/steps/tools/pipx,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-python-libs

COPY --link --from=tool-python /out/ /

RUN --mount=type=bind,from=steps,source=/steps/tools/python-libs,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-rust

RUN --mount=type=bind,from=steps,source=/steps/tools/rust,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-cargo-tools

COPY --link --from=tool-rust /out/ /

RUN --mount=type=bind,from=steps,source=/steps/tools/cargo-tools,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    --mount=type=cache,id=libre-box-cargo-git-${TARGETARCH},target=/opt/cargo/git,sharing=locked \
    --mount=type=cache,id=libre-box-cargo-registry-${TARGETARCH},target=/opt/cargo/registry,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-standard AS tool-version-managers

RUN --mount=type=bind,from=steps,source=/steps/tools/version-managers,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-standard AS standard

COPY --link --from=tool-chrome /out/ /
COPY --link --from=tool-cli /out/ /
COPY --link --from=tool-node /out/ /
COPY --link --from=tool-python /out/ /
COPY --link --from=tool-cloud /out/ /
COPY --link --from=tool-databases /out/ /
COPY --link --from=tool-docs /out/ /
COPY --link --from=tool-go /out/ /
COPY --link --from=tool-java /out/ /
COPY --link --from=tool-node-globals /out/ /
COPY --link --from=tool-pipx /out/ /
COPY --link --from=tool-python-libs /out/ /
COPY --link --from=tool-rust /out/ /
COPY --link --from=tool-cargo-tools /out/ /
COPY --link --from=tool-version-managers /out/ /

RUN --network=none \
    --mount=type=bind,source=finalize-image.sh,target=/build/finalize-image.sh \
    --mount=type=bind,source=inventory.py,target=/build/inventory.py \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/finalize-image.sh standard


FROM system-standard AS system-full

RUN --mount=type=bind,from=steps,source=/steps/system/full,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-apt-archives-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=libre-box-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    bash /build/lib/run-system-step.sh

RUN --mount=type=bind,from=steps,source=/steps/system/security,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-apt-archives-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=libre-box-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    bash /build/lib/run-system-step.sh


FROM system-full AS tool-languages

RUN --mount=type=bind,from=steps,source=/steps/tools/languages,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-full AS tool-python-ml

COPY --link --from=tool-python /out/ /
COPY --link --from=tool-python-libs /out/ /

RUN --mount=type=bind,from=steps,source=/steps/tools/python-ml,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-full AS security-cargo

COPY --link --from=tool-rust /out/ /
COPY --link --from=tool-cargo-tools /out/ /

RUN --mount=type=bind,from=steps,source=/steps/security/cargo,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    --mount=type=cache,id=libre-box-cargo-git-${TARGETARCH},target=/opt/cargo/git,sharing=locked \
    --mount=type=cache,id=libre-box-cargo-registry-${TARGETARCH},target=/opt/cargo/registry,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-full AS security-gems

RUN --mount=type=bind,from=steps,source=/steps/security/gems,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-full AS security-ghidra

COPY --link --from=tool-java /out/ /

RUN --mount=type=bind,from=steps,source=/steps/security/ghidra,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-full AS security-git

COPY --link --from=tool-python /out/ /
COPY --link --from=security-gems /out/ /

RUN --mount=type=bind,from=steps,source=/steps/security/git,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-full AS security-go

COPY --link --from=tool-go /out/ /

RUN --mount=type=bind,from=steps,source=/steps/security/go,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    --mount=type=cache,id=libre-box-go-modules-${TARGETARCH},target=/opt/gopath/pkg/mod,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-full AS security-metasploit

RUN --mount=type=bind,from=steps,source=/steps/security/metasploit,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-full AS security-pipx

COPY --link --from=tool-python /out/ /
COPY --link --from=tool-pipx /out/ /
COPY --link --from=tool-rust /out/ /

RUN --mount=type=bind,from=steps,source=/steps/security/pipx,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    --mount=type=cache,id=libre-box-cache-${TARGETARCH},target=/opt/state/cache,sharing=locked \
    bash /build/lib/run-step.sh


FROM system-full AS security-releases

RUN --mount=type=bind,from=steps,source=/steps/security/releases,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-full AS security-seclists

RUN --mount=type=bind,from=steps,source=/steps/security/seclists,target=/build \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/lib/run-step.sh


FROM system-full AS full

COPY --link --from=tool-chrome /out/ /
COPY --link --from=tool-cli /out/ /
COPY --link --from=tool-node /out/ /
COPY --link --from=tool-python /out/ /
COPY --link --from=tool-cloud /out/ /
COPY --link --from=tool-databases /out/ /
COPY --link --from=tool-docs /out/ /
COPY --link --from=tool-go /out/ /
COPY --link --from=tool-java /out/ /
COPY --link --from=tool-node-globals /out/ /
COPY --link --from=tool-pipx /out/ /
COPY --link --from=tool-python-libs /out/ /
COPY --link --from=tool-rust /out/ /
COPY --link --from=tool-cargo-tools /out/ /
COPY --link --from=tool-version-managers /out/ /
COPY --link --from=tool-languages /out/ /
COPY --link --from=tool-python-ml /out/ /
COPY --link --from=security-cargo /out/ /
COPY --link --from=security-gems /out/ /
COPY --link --from=security-ghidra /out/ /
COPY --link --from=security-git /out/ /
COPY --link --from=security-go /out/ /
COPY --link --from=security-metasploit /out/ /
COPY --link --from=security-pipx /out/ /
COPY --link --from=security-releases /out/ /
COPY --link --from=security-seclists /out/ /

RUN --network=none \
    --mount=type=bind,source=finalize-image.sh,target=/build/finalize-image.sh \
    --mount=type=bind,source=inventory.py,target=/build/inventory.py \
    --mount=type=tmpfs,target=/tmp \
    --mount=type=tmpfs,target=/root \
    bash /build/finalize-image.sh full