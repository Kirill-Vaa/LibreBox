#!/usr/bin/env bash

install_hashicorp_tool() {
    local name="$1"
    local version="$2"
    download "https://releases.hashicorp.com/${name}/${version}/${name}_${version}_linux_$(dpkg --print-architecture).zip" "/tmp/${name}.zip"
    unzip -q -o "/tmp/${name}.zip" "${name}" -d /usr/local/bin
}

install_step() {
    local architecture
    architecture="$(dpkg --print-architecture)"
    local machine
    machine="$(by_architecture x86_64 aarch64)"

    download "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-${architecture}.tar.gz" /tmp/age.tgz
    tar -xzf /tmp/age.tgz -C /usr/local/bin --strip-components=1 age/age age/age-keygen

    download "https://awscli.amazonaws.com/awscli-exe-linux-${machine}-${AWSCLI_VERSION}.zip" /tmp/awscli.zip
    unzip -q /tmp/awscli.zip -d /tmp
    /tmp/aws/install --install-dir /usr/local/aws-cli --bin-dir /usr/local/bin

    download "https://download.docker.com/linux/static/stable/${machine}/docker-${DOCKER_VERSION}.tgz" /tmp/docker.tgz
    tar -xzf /tmp/docker.tgz -C /usr/local/bin --strip-components=1 docker/docker
    mkdir -p /usr/local/lib/docker/cli-plugins
    download "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${machine}" /usr/local/lib/docker/cli-plugins/docker-compose
    chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose

    download "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${architecture}.tar.gz" /tmp/helm.tgz
    tar -xzf /tmp/helm.tgz -C /usr/local/bin --strip-components=1 "linux-${architecture}/helm"

    download "https://github.com/derailed/k9s/releases/download/v${K9S_VERSION}/k9s_Linux_${architecture}.tar.gz" /tmp/k9s.tgz
    tar -xzf /tmp/k9s.tgz -C /usr/local/bin k9s

    download "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/${architecture}/kubectl" /usr/local/bin/kubectl
    chmod 0755 /usr/local/bin/kubectl

    download "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv${KUSTOMIZE_VERSION}/kustomize_v${KUSTOMIZE_VERSION}_linux_${architecture}.tar.gz" /tmp/kustomize.tgz
    tar -xzf /tmp/kustomize.tgz -C /usr/local/bin kustomize

    install_hashicorp_tool packer "${PACKER_VERSION}"

    download "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.${architecture}" /usr/local/bin/sops
    chmod 0755 /usr/local/bin/sops

    install_hashicorp_tool terraform "${TERRAFORM_VERSION}"

    download "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_${architecture}.tar.gz" /tmp/tofu.tgz
    tar -xzf /tmp/tofu.tgz -C /usr/local/bin tofu

    install_hashicorp_tool vault "${VAULT_VERSION}"

    age --version
    aws --version
    docker --version
    docker compose version
    helm version --short
    k9s version -s
    kubectl version --client
    kustomize version
    packer version
    sops --version --disable-version-check
    terraform version
    tofu version
    vault version
}