# syntax=docker/dockerfile:1.7
# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
# Imagem multi-arquitetura (linux/amd64 e linux/arm64) construída SEM emulação (QEMU).
#
# Estágio 1 (sempre na arquitetura do host de build): baixa as wheels da arquitetura ALVO com
# `pip --platform`, sem executar nenhum código dela. Se alguma dependência não tiver wheel para a
# arquitetura, o build falha aqui, o que serve como prova de compatibilidade.
# Estágio 2 (arquitetura alvo): só copia arquivos. Não há instruções RUN, então o build
# para arm64 funciona em um notebook x86_64 e a imagem é a mesma que rodaria na Raspberry Pi 5.
ARG PYTHON_VERSION=3.12

FROM --platform=$BUILDPLATFORM python:${PYTHON_VERSION}-slim AS deps
ARG PYTHON_VERSION
ARG TARGETARCH
WORKDIR /w
COPY requirements.txt .
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) PLATFORMS="--platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform linux_x86_64";; \
      arm64) PLATFORMS="--platform manylinux_2_28_aarch64 --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 --platform linux_aarch64";; \
      *) echo "Arquitetura não suportada: $TARGETARCH" >&2; exit 1;; \
    esac; \
    pip install --no-cache-dir --disable-pip-version-check --only-binary=:all: \
        $PLATFORMS --python-version "$PYTHON_VERSION" --implementation cp --abi "cp$(echo "$PYTHON_VERSION" | tr -d .)" \
        --target /deps -r requirements.txt

FROM python:${PYTHON_VERSION}-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/deps
WORKDIR /srv
# UID numérico sem privilégios (não precisa de entrada em /etc/passwd)
COPY --chown=10001:10001 --from=deps /deps /deps
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 config ./config
COPY --chown=10001:10001 models ./models
USER 10001:10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
