#!/usr/bin/env bash
set -euo pipefail

package_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$PWD"
skip_downloader=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      [[ $# -ge 2 ]] || { echo "--workspace requires a directory." >&2; exit 2; }
      workspace="$2"
      shift 2
      ;;
    --skip-downloader-clone)
      skip_downloader=1
      shift
      ;;
    -h|--help)
      echo "Usage: ./install.sh [--workspace DIR] [--skip-downloader-clone]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$workspace"
workspace="$(cd "$workspace" && pwd)"
venv="$workspace/.venv"
downloader="$workspace/douyin-downloader"

if [[ ! -x "$venv/bin/python" ]]; then
  command -v python3 >/dev/null 2>&1 || { echo "Python 3.9 or newer is required." >&2; exit 2; }
  python3 -m venv "$venv"
fi

"$venv/bin/python" -m pip install --disable-pip-version-check --progress-bar off --upgrade pip
"$venv/bin/python" -m pip install --disable-pip-version-check --progress-bar off -r "$package_root/requirements.txt"
"$venv/bin/python" -m playwright install chromium
"$venv/bin/python" -m pip check

if [[ "$skip_downloader" -eq 0 && ! -f "$downloader/run.py" ]]; then
  command -v git >/dev/null 2>&1 || { echo "Git is required to download douyin-downloader." >&2; exit 2; }
  git clone https://github.com/jiji262/douyin-downloader.git "$downloader"
fi

if [[ -f "$downloader/config.example.yml" && ! -f "$downloader/config.yml" ]]; then
  cp "$downloader/config.example.yml" "$downloader/config.yml"
  echo "Created config.yml from config.example.yml. Complete local login configuration before processing."
fi

echo "Running readiness diagnostics..."
"$venv/bin/python" "$package_root/scripts/doctor.py" --workspace "$workspace"

echo "Installation complete. Finish Douyin login locally before processing favorites."
