#!/usr/bin/env bash

install_step() {
    clone_repository https://github.com/pyenv/pyenv.git "${PYENV_ROOT}" "v${PYENV_RELEASE}"

    "${PYENV_ROOT}/bin/pyenv" --version
}