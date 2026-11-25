#!/bin/sh
set -eu

node /app/libre-box/merge-config.js \
    /app/config/librechat.yaml \
    /app/config/librechat.override.yaml \
    "${CONFIG_PATH}"

exec docker-entrypoint.sh "$@"