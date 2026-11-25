#!/usr/bin/env bash
# Publish the FLUX one-take video as a public GitHub release asset.
#
#   ./publish_take.sh /path/to/flux_take.mp4
#
# Why a release and not an email attachment: a 20–60 minute screen recording
# is roughly 150 MB, and Gmail refuses anything over 25 MB. The build book
# allows a link ("Attach: video (or link) + CV"), and a release asset is ours,
# permanent, and public — the reviewer can open it in any browser.
#
# Prints the public download URL at the end — paste that into the email.

set -euo pipefail

TAKE="${1:-}"
REPO="llakterian/flux"
TAG="one-take"
ASSET="fluxharness_one_take.mp4"

if [[ -z "$TAKE" || ! -f "$TAKE" ]]; then
  echo "usage: $0 /path/to/take.mp4" >&2
  exit 1
fi

SIZE_BYTES=$(stat -c %s "$TAKE")
SIZE_MB=$((SIZE_BYTES / 1024 / 1024))
DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TAKE")
echo "==> $TAKE — ${SIZE_MB} MB, ${DURATION}s"

if (( SIZE_MB > 2000 )); then
  echo "ERROR: GitHub release assets cap at 2 GB; this file is ${SIZE_MB} MB." >&2
  exit 1
fi

echo "==> uploading to $REPO release '$TAG'"
if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  gh release upload "$TAG" "$TAKE#$ASSET" -R "$REPO" --clobber
else
  gh release create "$TAG" "$TAKE#$ASSET" -R "$REPO" \
    --title "FLUX one-take build video — fluxharness" \
    --notes "The one-take build video for the DirectMeds FLUX application: fluxharness, recorded continuously in one pass, no cuts. README has the details."
fi

URL="https://github.com/$REPO/releases/download/$TAG/$ASSET"
echo "==> public URL: $URL"
echo "==> check it:  curl -sIL \"$URL\" | head -5"
