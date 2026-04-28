FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ARG TERRAFORM_VERSION=1.14.8-1

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    unzip \
    gnupg \
    lsb-release \
    software-properties-common \
 && rm -rf /var/lib/apt/lists/*

# Terraform
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo $VERSION_CODENAME) main" \
    > /etc/apt/sources.list.d/hashicorp.list \
 && apt-get update \
 && apt-get install -y terraform=${TERRAFORM_VERSION} \
 && rm -rf /var/lib/apt/lists/*

# AWS CLI v2
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
 && unzip awscliv2.zip \
 && ./aws/install \
 && rm -rf aws awscliv2.zip

ENV APP_HOME /work
WORKDIR ${APP_HOME}

CMD ["/bin/bash"]
