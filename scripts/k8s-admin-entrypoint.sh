#!/bin/sh
set -eu

REPO="${CONTENT_REPO_PATH:-/content/akisok-site}"
SITE_BRANCH="${SITE_GIT_BRANCH:-main}"
TOKEN="${GIT_TOKEN:-${GITHUB_TOKEN:-}}"

export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-akisok-bot}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-akisok-bot@keresifon.com}"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

if [ -n "$TOKEN" ]; then
  SITE_REMOTE="https://x-access-token:${TOKEN}@github.com/kere-sifon/akisok-site.git"
else
  KEY="${GIT_SSH_KEY_PATH:-/var/run/secrets/git-ssh/id_ed25519}"
  SSH_DIR="${HOME:-/tmp}/.ssh"
  install -d -m 700 "$SSH_DIR"
  if [ ! -f "$KEY" ]; then
    echo "Set GIT_TOKEN (HTTPS) or mount an SSH deploy key at $KEY" >&2
    exit 1
  fi
  cp "$KEY" "$SSH_DIR/id_ed25519"
  chmod 600 "$SSH_DIR/id_ed25519"
  if [ ! -f "$SSH_DIR/known_hosts" ]; then
    ssh-keyscan github.com >> "$SSH_DIR/known_hosts" 2>/dev/null
  fi
  export GIT_SSH_COMMAND="ssh -i $SSH_DIR/id_ed25519 -o UserKnownHostsFile=$SSH_DIR/known_hosts -o StrictHostKeyChecking=yes"
  SITE_REMOTE="${SITE_GIT_REMOTE:-git@github.com:kere-sifon/akisok-site.git}"
fi

if [ ! -d "$REPO/.git" ]; then
  git clone --branch "$SITE_BRANCH" "$SITE_REMOTE" "$REPO"
else
  git -C "$REPO" remote set-url origin "$SITE_REMOTE"
  git -C "$REPO" fetch origin
  git -C "$REPO" checkout "$SITE_BRANCH"
  git -C "$REPO" pull --rebase origin "$SITE_BRANCH"
fi

git -C "$REPO" config user.name "$GIT_AUTHOR_NAME"
git -C "$REPO" config user.email "$GIT_AUTHOR_EMAIL"

exec uvicorn src.admin.main:app --host "${ADMIN_UI_HOST:-0.0.0.0}" --port "${ADMIN_UI_PORT:-8001}"
