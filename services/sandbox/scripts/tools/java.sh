#!/usr/bin/env bash

install_step() {
    download "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" /tmp/gradle.zip
    unzip -q /tmp/gradle.zip -d /opt
    mv "/opt/gradle-${GRADLE_VERSION}" /opt/gradle
    ln -sf /opt/gradle/bin/gradle /usr/local/bin/gradle

    GRADLE_USER_HOME=/tmp/gradle-home /opt/gradle/bin/gradle --version -Dorg.gradle.welcome=never
}