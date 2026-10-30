#!/usr/bin/env bash

install_step() {
    apt_install \
        buildah default-libmysqlclient-dev ffmpeg fonts-firacode fonts-freefont-ttf \
        fonts-jetbrains-mono fonts-noto-extra ghostscript gifsicle graphicsmagick graphviz \
        imagemagick img2pdf inkscape jpegoptim latexmk libbz2-dev libffi-dev libgdbm-compat-dev \
        libgdbm-dev libimage-exiftool-perl liblzma-dev libncurses-dev libpq-dev libreadline-dev \
        librsvg2-bin libsndfile1 libsqlite3-dev libssl-dev libvips-tools libzstd-dev \
        mariadb-client maven mupdf-tools "openjdk-${JAVA_VERSION}-jdk" optipng pandoc \
        pdftk-java pipx plantuml pngquant poppler-utils postgresql-client potrace python3-dev \
        qpdf redis-tools skopeo sox sqlite3 tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd \
        tesseract-ocr-rus texlive-latex-base tk-dev unixodbc-dev uuid-dev webp zlib1g-dev

    fc-cache -f

    require_commands buildah dot exiftool ffmpeg gm gs javac latexmk magick mariadb mutool mvn pandoc pdflatex pdftk pdftotext pipx plantuml psql qpdf redis-cli skopeo sqlite3 tesseract vips
}