#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GLIBC_VARIANT="${1:-glibc217}"
DOCKERFILE_PATH="${REPO_ROOT}/packaging/linux/Dockerfile.${GLIBC_VARIANT}"
IMAGE_NAME="${ALRED_DOCKER_IMAGE:-alred-build-${GLIBC_VARIANT}}"
PYTHON_BIN="${ALRED_DOCKER_PYTHON_BIN:-/opt/python-shared/cp311/bin/python3.11}"
DOCKER_BUILD_ARGS=()

if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
  echo "dockerfile not found: ${DOCKERFILE_PATH}" >&2
  exit 1
fi

if [[ "${ALRED_DOCKER_BUILD_NO_CACHE:-0}" == "1" ]]; then
  DOCKER_BUILD_ARGS+=(--no-cache)
fi

docker build \
  "${DOCKER_BUILD_ARGS[@]}" \
  -f "${DOCKERFILE_PATH}" \
  -t "${IMAGE_NAME}" \
  "${REPO_ROOT}"

docker run --rm \
  -v "${REPO_ROOT}:/work" \
  -w /work \
  "${IMAGE_NAME}" \
  /bin/bash -lc "
    set -euo pipefail
    rm -rf build
    rm -f dist/alred dist/alred.exe
    ${PYTHON_BIN} -m PyInstaller --clean --noconfirm alred.spec
    chown -R $(id -u):$(id -g) build dist
  "
