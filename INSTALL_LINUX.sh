#!/usr/bin/env bash
set -u

cd "$(dirname "$0")" || {
  echo "Could not open installer folder."
  exit 1
}

if [[ ! -f "scripts/install_linux.sh" ]]; then
  echo "Could not find scripts/install_linux.sh."
  echo "Make sure you extracted the full release ZIP before running this file."
  exit 1
fi

bash "scripts/install_linux.sh" "$@"
