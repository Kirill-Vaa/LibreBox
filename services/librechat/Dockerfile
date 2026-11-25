# syntax=docker/dockerfile:1

ARG LIBRECHAT_BASE_IMAGE

FROM ${LIBRECHAT_BASE_IMAGE}

RUN --mount=type=bind,source=apply-patches.js,target=/build-input/apply-patches.js \
    node /build-input/apply-patches.js