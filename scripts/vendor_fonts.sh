#!/usr/bin/env bash
# =============================================================================
# vendor_fonts.sh — one-shot download of Google Fonts WOFF2 files
# =============================================================================
# Downloads the 17 WOFF2 files referenced by the previous CDN-loaded
# `fonts.googleapis.com/css2?family=Orbitron|Rajdhani|Share+Tech+Mono` import
# and stores them under static/fonts/. After this runs, the CSS rewrite
# (static/css/core/fonts.css) replaces the gstatic.com URLs with local
# /static/fonts/<filename> references.
#
# Idempotent: re-running skips files already on disk. Validates each
# downloaded file by checking the WOFF2 magic header ("wOF2"); a partial or
# captive-portal-redirected download is detected and reported.
# =============================================================================

set -euo pipefail

# Resolve project root (parent of scripts/).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)"
FONT_DIR="$PROJECT_ROOT/static/fonts"

mkdir -p "$FONT_DIR"
cd "$FONT_DIR"

# Modern Chrome UA so gstatic serves WOFF2 (older UAs get TTF).
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'

URLS=(
  # Orbitron — single variable-font file covers all 6 weights (400-900).
  https://fonts.gstatic.com/s/orbitron/v35/yMJRMIlzdpvBhQQL_Qq7dy0.woff2
  # Rajdhani — 5 weights (300/400/500/600/700) × 3 unicode-range subsets
  # (latin / latin-ext / vietnamese) = 15 files. Each subset only loads when
  # the page actually renders that codepoint range.
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pasEfOleef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pasEfOqeef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pasEfOreec.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDIxapCSOBg7S-QT7p4GM-aUWA.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDIxapCSOBg7S-QT7p4HM-Y.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDIxapCSOBg7S-QT7p4JM-aUWA.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pb0EPOleef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pb0EPOqeef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pb0EPOreec.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pbYF_Oleef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pbYF_Oqeef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pbYF_Oreec.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pa8FvOleef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pa8FvOqeef2kg.woff2
  https://fonts.gstatic.com/s/rajdhani/v17/LDI2apCSOBg7S-QT7pa8FvOreec.woff2
  # Share Tech Mono — single weight (400), single subset.
  https://fonts.gstatic.com/s/sharetechmono/v16/J7aHnp1uDWRBEqV98dVQztYldFcLowEF.woff2
)

echo "Vendoring ${#URLS[@]} WOFF2 files into $FONT_DIR ..."
echo

ok=0
skipped=0
failed=0

for url in "${URLS[@]}"; do
  fname="$(basename "$url")"

  if [[ -s "$fname" ]]; then
    # Skip if already present and non-empty.
    size=$(stat -c%s "$fname")
    printf "  [skip] %-60s %6d bytes (exists)\n" "$fname" "$size"
    skipped=$((skipped + 1))
    continue
  fi

  if curl -fsSL -A "$UA" "$url" -o "$fname.tmp"; then
    # Verify WOFF2 magic header: bytes 0..3 must be "wOF2" (0x77 0x4F 0x46 0x32).
    magic=$(head -c 4 "$fname.tmp" | od -An -c | tr -d ' \n')
    if [[ "$magic" == "wOF2" ]]; then
      mv "$fname.tmp" "$fname"
      size=$(stat -c%s "$fname")
      printf "  [ok]   %-60s %6d bytes\n" "$fname" "$size"
      ok=$((ok + 1))
    else
      rm -f "$fname.tmp"
      printf "  [FAIL] %-60s wrong magic: %s\n" "$fname" "$magic"
      failed=$((failed + 1))
    fi
  else
    rm -f "$fname.tmp"
    printf "  [FAIL] %-60s curl failed\n" "$fname"
    failed=$((failed + 1))
  fi
done

echo
echo "Done. ok=$ok  skipped=$skipped  failed=$failed"

if [[ $failed -gt 0 ]]; then
  exit 1
fi
