#!/usr/bin/env bash
# Build a deployable image archive from this checkout.
#
# This script only touches the local machine. It never connects to the
# production host and never reads or writes the remote accounts/usage data.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${DIST_DIR:-$ROOT_DIR/dist}"
IMAGE="${IMAGE:-localhost/workbuddy2api-hub:latest}"
PLATFORM="${PLATFORM:-linux/arm64}"
# Docker Hub is not reachable from every development network. The Google
# mirror serves the same upstream image and can be overridden with BASE_IMAGE.
BASE_IMAGE="${BASE_IMAGE:-mirror.gcr.io/library/python:3.11-alpine}"
ARCHIVE_BASENAME="${ARCHIVE_BASENAME:-workbuddy2api-hub-linux-arm64}"
ARCHIVE="$DIST_DIR/$ARCHIVE_BASENAME.tar.gz"
METADATA="$DIST_DIR/$ARCHIVE_BASENAME.metadata.json"
TMP_ARCHIVE="$ARCHIVE.tmp"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

die() {
  printf 'package-image: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

need podman
need git
need gzip
need shasum
need "$PYTHON_BIN"

if [[ ! -f "$ROOT_DIR/Dockerfile" ]]; then
  die "Dockerfile not found under $ROOT_DIR"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  printf '\n[0/4] creating packaging venv at %s\n' "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if [[ -f "$ROOT_DIR/requirements-packaging.txt" ]]; then
  "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -q \
    -r "$ROOT_DIR/requirements-packaging.txt"
fi

if [[ -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal 2>/dev/null || true)" ]]; then
  printf 'package-image: warning: git worktree is not clean\n' >&2
fi

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  printf '\n[1/4] running regression tests\n'
  (
    cd "$ROOT_DIR"
    "$VENV_DIR/bin/python" _test_custom_tools.py
    "$VENV_DIR/bin/python" _test_model_cooldown.py
    "$VENV_DIR/bin/python" _test_model_config.py
    "$VENV_DIR/bin/python" _test_usage_key.py
    "$VENV_DIR/bin/python" _test_account_display.py
    "$VENV_DIR/bin/python" _test_cat_travel.py
  )
else
  printf '\n[1/4] regression tests skipped (SKIP_TESTS=1)\n'
fi

mkdir -p "$DIST_DIR"
rm -f "$TMP_ARCHIVE"

GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || printf 'unknown')"
BUILT_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

printf '\n[2/4] building %s for %s\n' "$IMAGE" "$PLATFORM"
printf '       base image: %s\n' "$BASE_IMAGE"
podman build \
  --platform "$PLATFORM" \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --tag "$IMAGE" \
  "$ROOT_DIR"

IMAGE_ID="$(podman image inspect "$IMAGE" --format '{{.Id}}')"

printf '\n[3/4] exporting image archive\n'
podman save --format docker-archive -o "$TMP_ARCHIVE" "$IMAGE"
mv "$TMP_ARCHIVE" "$ARCHIVE"
SHA256="$(LC_ALL=C shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
SIZE_BYTES="$(wc -c < "$ARCHIVE" | tr -d ' ')"

printf '\n[4/4] writing metadata\n'
cat > "$METADATA" <<EOF
{
  "image": "$IMAGE",
  "image_id": "$IMAGE_ID",
  "platform": "$PLATFORM",
  "base_image": "$BASE_IMAGE",
  "archive": "$(basename "$ARCHIVE")",
  "sha256": "$SHA256",
  "size_bytes": $SIZE_BYTES,
  "git_commit": "$GIT_COMMIT",
  "built_at": "$BUILT_AT"
}
EOF

printf '\npackage ready\n'
printf '  archive : %s\n' "$ARCHIVE"
printf '  metadata: %s\n' "$METADATA"
printf '  sha256  : %s\n' "$SHA256"
printf '  image   : %s (%s)\n' "$IMAGE" "$IMAGE_ID"
printf '\ndeploy with:\n  scripts/deploy-production.sh\n'
