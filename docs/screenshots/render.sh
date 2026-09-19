#!/usr/bin/env bash
set -euo pipefail

# Usage: docs/screenshots/render.sh (run from the repo root)

dir="docs/screenshots"
work="$(mktemp -d)"
tmp_configs=()

cleanup() {
  rm -rf "$work"
  for tmp in "${tmp_configs[@]}"; do
    rm -f "$tmp"
  done
}
trap cleanup EXIT

for shot in search own stars user context; do
  for theme in dark light; do
    tmp="$dir/.${shot}-${theme}.json"
    tmp_configs+=("$tmp")
    jq --arg css "win11-${theme}.css" '. + {css: $css}' "$dir/${shot}.json" > "$tmp"
    out="$work/${shot}-${theme}"
    mkdir -p "$out"
    flow-render -c "$tmp" -o "$out"
    mv "$out"/*.png "$dir/${shot}-${theme}.png"
    rm -f "$tmp"
  done
done
