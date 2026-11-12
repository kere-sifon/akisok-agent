#!/usr/bin/env bash
# Build, push and roll out akisok-agent (admin + pipeline) to homelab-k8s.
#   deploy/deploy.sh            build + push + deploy
#   deploy/deploy.sh build      build + push only
#   deploy/deploy.sh apply      deploy an existing tag
#   deploy/deploy.sh secrets    namespace + agent env + pull secret
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

REGISTRY="${REGISTRY:-nexus-lan.keresifon.com}"
IMAGE="${IMAGE:-$REGISTRY/docker-hosted/akisok-agent}"
NAMESPACE="akisok"
APP_URL="${APP_URL:-http://192.168.2.245:8001/}"
ENV_FILE="${ENV_FILE:-.env}"
GIT_SSH_KEY_FILE="${GIT_SSH_KEY_FILE:-$HOME/.config/akisok/id_ed25519}"
KEYCHAIN_SERVICE="${KEYCHAIN_SERVICE:-nexus-k8s-pull}"
export KUBECONFIG="${KUBECONFIG:-$HOME/homelab-k8s/kubeconfig}"

if [[ -z "${TAG:-}" ]]; then
  TAG="$(git rev-parse --short HEAD 2>/dev/null || echo latest)"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && [[ -n "$(git status --porcelain)" ]]; then
    TAG="$TAG-dirty-$(date +%Y%m%d%H%M%S)"
  fi
fi

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

build() {
  log "Building $IMAGE:$TAG (linux/amd64) and pushing"
  docker buildx build --platform linux/amd64 -t "$IMAGE:$TAG" --push .
}

sync_secrets() {
  if [[ "${SYNC_SECRETS:-1}" == "0" ]]; then
    echo "SYNC_SECRETS=0: leaving cluster secrets as they are"; return 0
  fi
  kubectl apply -f deploy/k8s/namespace.yaml >/dev/null

  if [[ -f "$ENV_FILE" ]]; then
    log "Syncing akisok-agent-env from $ENV_FILE"
    kubectl -n "$NAMESPACE" create secret generic akisok-agent-env \
      --from-env-file="$ENV_FILE" --dry-run=client -o yaml | kubectl apply -f -
  else
    echo "No $ENV_FILE; skipping akisok-agent-env"
  fi

  if [[ -f "$GIT_SSH_KEY_FILE" ]]; then
    log "Syncing akisok-git-ssh from $GIT_SSH_KEY_FILE"
    kubectl -n "$NAMESPACE" create secret generic akisok-git-ssh \
      --from-file=id_ed25519="$GIT_SSH_KEY_FILE" --dry-run=client -o yaml | kubectl apply -f -
  else
    echo "No $GIT_SSH_KEY_FILE; create a write deploy key and:"
    echo "  kubectl -n $NAMESPACE create secret generic akisok-git-ssh --from-file=id_ed25519=PATH"
  fi

  if ! kubectl -n "$NAMESPACE" get secret nexus-pull >/dev/null 2>&1; then
    log "Creating nexus-pull secret"
    local pw="${NEXUS_PULL_PASSWORD:-}"
    if [[ -z "$pw" ]]; then
      pw="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)" || {
        echo "No k8s-pull password. Store it once with:"
        echo "  security add-generic-password -s $KEYCHAIN_SERVICE -a k8s-pull -w"
        exit 1
      }
    fi
    kubectl -n "$NAMESPACE" create secret docker-registry nexus-pull \
      --docker-server="$REGISTRY" --docker-username=k8s-pull --docker-password="$pw" >/dev/null
  fi
}

apply() {
  sync_secrets
  log "Applying manifests with image $IMAGE:$TAG"
  kubectl kustomize deploy/k8s \
    | sed -E "s#(image: )$IMAGE:[^[:space:]]+#\1$IMAGE:$TAG#" \
    | kubectl apply -f -

  if [[ "${SYNC_SECRETS:-1}" != "0" && -f "$ENV_FILE" ]]; then
    local hash; hash="$( (sha256sum "$ENV_FILE" 2>/dev/null || shasum -a 256 "$ENV_FILE") | cut -c1-16)"
    kubectl -n "$NAMESPACE" patch deploy/akisok-admin --type merge \
      -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"deploy.homelab/env-hash\":\"$hash\"}}}}}" >/dev/null
  fi

  log "Waiting for admin rollout"
  if ! kubectl -n "$NAMESPACE" rollout status deploy/akisok-admin --timeout=5m; then
    echo "Rollout failed. Recent events:"
    kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -15
    echo "Roll back with: make rollback"
    exit 1
  fi

  log "Health check $APP_URL"
  for _ in {1..15}; do
    if curl -fsS -o /dev/null "$APP_URL"; then echo "OK: $IMAGE:$TAG is live"; return 0; fi
    sleep 3
  done
  echo "Health check failed"; exit 1
}

case "${1:-all}" in
  build)   build ;;
  secrets) sync_secrets ;;
  apply)   apply ;;
  all)     build; apply ;;
  *) echo "usage: $0 [all|build|apply|secrets]"; exit 2 ;;
esac
