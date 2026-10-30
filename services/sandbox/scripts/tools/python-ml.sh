#!/usr/bin/env bash

install_step() {
    log_refresh "${PACKAGES_REFRESH}"
    rm -f /opt/pytools/pip.conf

    uv pip install --python /opt/pytools/bin/python --constraints /opt/pytools/constraints.txt \
        --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
        torch torchvision
    uv pip install --python /opt/pytools/bin/python --constraints /opt/pytools/constraints.txt \
        catboost easyocr lightgbm sentence-transformers spacy transformers xgboost

    freeze_pytools

    /opt/pytools/bin/python -c 'import torch, torchvision, catboost, easyocr, lightgbm, sentence_transformers, spacy, transformers, xgboost'
}