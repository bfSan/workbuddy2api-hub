#!/usr/bin/env bash
# Deploy a locally packaged image to the production Podman host.
#
# Local mode:
#   scripts/deploy-production.sh [archive.tar.gz]
#
# The archive defaults to dist/workbuddy2api-hub-linux-arm64.tar.gz. The
# remote container is replaced only after the new image has loaded. If the
# new container does not become healthy, the previous image is started again.
#
# Remote mode is used internally after this script and the archive have been
# copied to the server. It never copies accounts, usage logs, or credentials.
set -euo pipefail

die() {
  printf 'deploy-production: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

if [[ "${DEPLOY_REMOTE_MODE:-0}" == "1" ]]; then
  : "${DEPLOY_ARCHIVE:?DEPLOY_ARCHIVE is required in remote mode}"
  : "${DEPLOY_IMAGE:?DEPLOY_IMAGE is required in remote mode}"
  : "${DEPLOY_SHA256:?DEPLOY_SHA256 is required in remote mode}"

  PODMAN_BIN="${PODMAN_BIN:-/opt/podman/bin/podman}"
  CONTAINER_NAME="${CONTAINER_NAME:-wb-proxy}"
  HOST_PORT="${HOST_PORT:-8788}"
  DATA_DIR="${DATA_DIR:-$HOME/services/hub-data}"
  ACCOUNTS_DIR_REMOTE="$DATA_DIR/accounts"
  USAGE_DIR_REMOTE="$DATA_DIR/usage"
  CACHE_FILE="$DATA_DIR/wbcache/acc-product-config-v3.json"
  CACHE_TARGET="/root/.workbuddy/cache/acc-product-config-v3.json"
  PANEL_PASSWORD_FILE="${PANEL_PASSWORD_FILE:-$DATA_DIR/PANEL_PASSWORD.txt}"
  ROLLBACK_IMAGE="localhost/workbuddy2api-hub:rollback"
  HEALTH_URL="http://127.0.0.1:$HOST_PORT/health"
  MODELS_URL="http://127.0.0.1:$HOST_PORT/settings/models"

  command -v "$PODMAN_BIN" >/dev/null 2>&1 || die "podman not found: $PODMAN_BIN"
  command -v curl >/dev/null 2>&1 || die "curl not found on remote host"
  command -v python3 >/dev/null 2>&1 || die "python3 not found on remote host"
  [[ -r "$DEPLOY_ARCHIVE" ]] || die "archive is not readable: $DEPLOY_ARCHIVE"
  [[ -r "$PANEL_PASSWORD_FILE" ]] || die "panel password file is not readable: $PANEL_PASSWORD_FILE"
  [[ -d "$ACCOUNTS_DIR_REMOTE" ]] || die "accounts directory not found: $ACCOUNTS_DIR_REMOTE"
  [[ -d "$USAGE_DIR_REMOTE" ]] || die "usage directory not found: $USAGE_DIR_REMOTE"
  [[ -r "$CACHE_FILE" ]] || die "model cache file not readable: $CACHE_FILE"

  ACTUAL_SHA="$(LC_ALL=C shasum -a 256 "$DEPLOY_ARCHIVE" | awk '{print $1}')"
  [[ "$ACTUAL_SHA" == "$DEPLOY_SHA256" ]] || die "archive checksum mismatch"

  printf '\n[remote 1/5] loading image %s\n' "$DEPLOY_IMAGE"
  old_image_id=""
  if "$PODMAN_BIN" container exists "$CONTAINER_NAME"; then
    old_image_id="$("$PODMAN_BIN" inspect "$CONTAINER_NAME" --format '{{.Image}}')"
    "$PODMAN_BIN" tag "$old_image_id" "$ROLLBACK_IMAGE"
  fi
  "$PODMAN_BIN" load -i "$DEPLOY_ARCHIVE"
  new_image_id="$("$PODMAN_BIN" image inspect "$DEPLOY_IMAGE" --format '{{.Id}}')"

  start_container() {
    local image_ref="$1"
    local panel_password
    panel_password="$(cat "$PANEL_PASSWORD_FILE")"

    "$PODMAN_BIN" run -d \
      --name "$CONTAINER_NAME" \
      --restart unless-stopped \
      -p "0.0.0.0:$HOST_PORT:$HOST_PORT" \
      -v "$ACCOUNTS_DIR_REMOTE:/app/accounts" \
      -v "$USAGE_DIR_REMOTE:/app/usage" \
      -v "$CACHE_FILE:$CACHE_TARGET:ro" \
      -e TZ=Asia/Shanghai \
      -e WB_PROXY_DEFAULT_REALM=cn \
      -e WB_MODEL_SET=official \
      -e HTTP_PROXY= \
      -e HTTPS_PROXY= \
      -e http_proxy= \
      -e https_proxy= \
      "$image_ref" python wb_proxy.py \
      --host 0.0.0.0 \
      --port "$HOST_PORT" \
      --panel-password "$panel_password" >/dev/null
  }

  wait_health() {
    local attempt
    for attempt in $(seq 1 30); do
      if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        return 0
      fi
      sleep 1
    done
    return 1
  }

  verify_panel_endpoint() {
    local login_json token models_json
    login_json="$(python3 -c 'import json,sys; print(json.dumps({"password": open(sys.argv[1]).read().strip()}))' "$PANEL_PASSWORD_FILE")"
    token="$(curl -fsS --max-time 5 \
      -H 'Content-Type: application/json' \
      -d "$login_json" \
      "http://127.0.0.1:$HOST_PORT/panel/login" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token", ""))')"
    [[ -n "$token" ]] || return 1
    models_json="$(curl -fsS --max-time 10 -H "X-Panel-Token: $token" "$MODELS_URL")"
    printf '%s' "$models_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ok") is True; assert set(d.get("realms", {})) >= {"intl", "cn"}; assert "pool" in d["realms"]["intl"] and "pool" in d["realms"]["cn"]'
  }

  rollback() {
    local failed=0
    printf '\nnew container failed verification; rolling back to %s\n' "$ROLLBACK_IMAGE" >&2
    "$PODMAN_BIN" logs --tail 100 "$CONTAINER_NAME" >&2 || true
    "$PODMAN_BIN" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    if [[ -n "$old_image_id" ]]; then
      start_container "$ROLLBACK_IMAGE" || failed=1
      if [[ "$failed" -eq 0 ]] && wait_health; then
        printf 'rollback health check: ok\n' >&2
      else
        printf 'rollback failed; manual attention required\n' >&2
      fi
    fi
    exit 1
  }

  trap rollback ERR

  printf '\n[remote 2/5] replacing %s\n' "$CONTAINER_NAME"
  "$PODMAN_BIN" rm -f "$CONTAINER_NAME" >/dev/null
  start_container "$DEPLOY_IMAGE"

  printf '\n[remote 3/5] waiting for /health\n'
  if ! wait_health; then
    printf 'health check timed out\n' >&2
    rollback
  fi

  printf '\n[remote 4/5] verifying model configuration endpoint\n'
  if ! verify_panel_endpoint; then
    printf 'panel endpoint verification failed\n' >&2
    rollback
  fi

  trap - ERR
  printf '\n[remote 5/5] deployment complete\n'
  printf '  container : %s\n' "$CONTAINER_NAME"
  printf '  image     : %s (%s)\n' "$DEPLOY_IMAGE" "$new_image_id"
  printf '  health    : %s\n' "$HEALTH_URL"
  exit 0
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/workbuddy2api-hub"
DEPLOY_ENV="${DEPLOY_ENV:-$DEFAULT_CONFIG_DIR/deploy.env}"

if [[ -f "$DEPLOY_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$DEPLOY_ENV"
fi

REMOTE_HOST="${REMOTE_HOST:-10.88.86.106}"
REMOTE_USER="${REMOTE_USER:-yunxing}"
SSH_PORT="${SSH_PORT:-22}"
REMOTE_BASE="${REMOTE_BASE:-/Users/$REMOTE_USER/services/deploy/incoming}"
IMAGE="${IMAGE:-localhost/workbuddy2api-hub:latest}"
ARCHIVE="${1:-${ARCHIVE:-$ROOT_DIR/dist/workbuddy2api-hub-linux-arm64.tar.gz}}"
SSH_PASSWORD_FILE="${SSH_PASSWORD_FILE:-$DEFAULT_CONFIG_DIR/ssh-password}"

need expect
need scp
need ssh
need gzip
need shasum
[[ -r "$ARCHIVE" ]] || die "archive not found: $ARCHIVE (run scripts/package-image.sh first)"

if [[ ! -r "$SSH_PASSWORD_FILE" && -r /tmp/sshpw ]]; then
  SSH_PASSWORD_FILE=/tmp/sshpw
fi
[[ -r "$SSH_PASSWORD_FILE" ]] || die "SSH password file is not readable: $SSH_PASSWORD_FILE"

SHA256="$(LC_ALL=C shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
STAMP="$(date '+%Y%m%d-%H%M%S')"
REMOTE_ARCHIVE="$REMOTE_BASE/workbuddy2api-hub-$STAMP.tar.gz"
REMOTE_SCRIPT="$REMOTE_BASE/deploy-production-$STAMP.sh"
EXPECT_RUNNER="$(mktemp "${TMPDIR:-/tmp}/wb-deploy-expect.XXXXXX")"
cleanup() { rm -f "$EXPECT_RUNNER"; }
trap cleanup EXIT

cat > "$EXPECT_RUNNER" <<'EXPECT'
#!/usr/bin/expect -f
set timeout -1
set password_file [lindex $argv 0]
set command [lrange $argv 1 end]
if {[catch {open $password_file r} fp]} {
    puts stderr "cannot open password file: $password_file"
    exit 2
}
set password [read $fp]
close $fp
set password [string trim $password "\r\n"]
spawn {*}$command
expect {
    -re "(?i)password:" { send -- "$password\r"; exp_continue }
    -re "Permission denied" { puts stderr "SSH authentication failed"; exit 3 }
    eof
}
catch wait result
exit [lindex $result 3]
EXPECT
chmod 700 "$EXPECT_RUNNER"

remote_ssh() {
  expect "$EXPECT_RUNNER" "$SSH_PASSWORD_FILE" \
    ssh -T \
      -p "$SSH_PORT" \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o PreferredAuthentications=password \
      -o PubkeyAuthentication=no \
      "$REMOTE_USER@$REMOTE_HOST" "$@"
}

remote_scp() {
  expect "$EXPECT_RUNNER" "$SSH_PASSWORD_FILE" \
    scp -q \
      -P "$SSH_PORT" \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o PreferredAuthentications=password \
      -o PubkeyAuthentication=no \
      "$@"
}

printf '\n[1/3] staging package on %s\n' "$REMOTE_HOST"
remote_ssh "mkdir -p '$REMOTE_BASE'"
remote_scp "$ARCHIVE" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_ARCHIVE"
remote_scp "${BASH_SOURCE[0]}" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_SCRIPT"

printf '\n[2/3] replacing production container\n'
remote_ssh \
  "DEPLOY_REMOTE_MODE=1 DEPLOY_ARCHIVE='$REMOTE_ARCHIVE' DEPLOY_IMAGE='$IMAGE' DEPLOY_SHA256='$SHA256' bash '$REMOTE_SCRIPT'"

printf '\n[3/3] deployment finished\n'
printf '  host    : %s\n' "$REMOTE_HOST"
printf '  archive : %s\n' "$REMOTE_ARCHIVE"
printf '  sha256  : %s\n' "$SHA256"

# The archive is already loaded into Podman storage. Keep a failed rollout's
# files for diagnosis, but remove the successful staging copies.
if ! remote_ssh "rm -f '$REMOTE_ARCHIVE' '$REMOTE_SCRIPT'"; then
  printf 'deploy-production: warning: failed to clean staging files on %s\n' "$REMOTE_HOST" >&2
fi
