#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

uv build --wheel

venv_dir="$(mktemp -d "${TMPDIR:-/tmp}/gcb-cli-venv.XXXXXX")"
trap 'rm -rf "${venv_dir}"' EXIT

uv venv --python 3.13 "${venv_dir}" >/dev/null
wheel="$(ls dist/4ok-*.whl | head -1)"
uv pip install --python "${venv_dir}/bin/python" --quiet "${wheel}"
# Verify gcb --help works from the standalone wheel-installed console script.
"${venv_dir}/bin/gcb" --help | grep -F "retrieve" >/dev/null
"${venv_dir}/bin/gcb" retrieve --help | grep -F "retrieval augmentation" >/dev/null
