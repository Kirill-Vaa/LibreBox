#!/usr/bin/env bash

install_step() {
    log_refresh "${PACKAGES_REFRESH}"
    rm -f /opt/pytools/pip.conf

    uv pip install --python /opt/pytools/bin/python \
        aiohttp altair audioop-lts beautifulsoup4 duckdb fpdf2 httpx imageio ipython jupyterlab \
        lxml matplotlib mutagen nltk numpy onnxruntime opencv-python-headless openpyxl pandas \
        parsel pikepdf Pillow plotly polars psycopg pyarrow pydub pymongo pymysql python-docx \
        python-pptx readability-lxml redis reportlab requests scikit-image scikit-learn scipy \
        scrapy seaborn selectolax sqlalchemy sqlite-utils sqlmodel statsmodels tabulate xlsxwriter

    /opt/pytools/bin/python -m nltk.downloader -d /opt/nltk_data punkt punkt_tab stopwords

    freeze_pytools
}