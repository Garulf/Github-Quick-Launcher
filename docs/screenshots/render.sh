#!/usr/bin/env bash
set -euo pipefail

# Usage: docs/screenshots/render.sh (run from the repo root)

dir="docs/screenshots"

for shot in search own stars user context; do
  for theme in dark light; do
    tmp="$dir/.${shot}-${theme}.json"
    jq --arg css "win11-${theme}.css" '. + {css: $css}' "$dir/${shot}.json" > "$tmp"
    out="$(mktemp -d)"
    flow-render -c "$tmp" -o "$out" --hide-caret
    mv "$out"/*.png "$dir/${shot}-${theme}.png"
    rm -f "$tmp"
    rmdir "$out"
  done
done
