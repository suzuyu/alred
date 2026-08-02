#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

run_step() {
  echo
  echo "==> $*"
  "$@"
}

cd "${REPO_ROOT}"

variants=(glibc217)

usage() {
  echo "usage: $0 [--variant glibc217|glibc228|glibc234] [--all-variants]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      case "$2" in
        glibc217|glibc228|glibc234)
          variants=("$2")
          ;;
        *)
          usage
          exit 2
          ;;
      esac
      shift 2
      ;;
    --all-variants)
      variants=(glibc217 glibc228 glibc234)
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

for variant in "${variants[@]}"; do
  run_step "${SCRIPT_DIR}/build_binary_glibc.sh" "${variant}"
  run_step "${REPO_ROOT}/dist/alred" --version
  run_step "${REPO_ROOT}/dist/alred" --help
  run_step \
    "${SCRIPT_DIR}/prepare_release_artifacts.sh" \
    dist/alred \
    "alred-linux-x86_64-${variant}"
done

echo
echo "completed Linux x86_64 release artifact build flow: ${variants[*]}"
