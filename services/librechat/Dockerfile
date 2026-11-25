# syntax=docker/dockerfile:1

ARG LIBRECHAT_BASE_IMAGE

FROM ${LIBRECHAT_BASE_IMAGE}

RUN --mount=type=bind,source=apply-patches.js,target=/build-input/apply-patches.js \
    node /build-input/apply-patches.js

COPY merge-config.js /app/libre-box/merge-config.js
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

ENV CONFIG_PATH=/tmp/librechat.yaml

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]