#!/usr/bin/env bash
#   deploy/ci/make-kubeconfig.sh | gh secret set KUBE_CONFIG_B64 -R kere-sifon/akisok-agent
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/homelab-k8s/kubeconfig}"
NS=akisok
SECRET=github-deployer-agent-token

SERVER="${API_SERVER:-$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')}"
[ -n "$SERVER" ] || { echo "Could not determine API server; set API_SERVER=..." >&2; exit 1; }

TOKEN=""
for _ in $(seq 1 10); do
  TOKEN="$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.token}' 2>/dev/null | base64 --decode || true)"
  [ -n "$TOKEN" ] && break
  sleep 2
done
[ -n "$TOKEN" ] || {
  echo "Secret $NS/$SECRET has no token. Did you 'kubectl apply -f deploy/ci/rbac.yaml'?" >&2
  exit 1
}
CA="$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.ca\.crt}')"

cat <<KCFG | base64 | tr -d '\n'
apiVersion: v1
kind: Config
clusters:
  - name: homelab
    cluster:
      server: $SERVER
      certificate-authority-data: $CA
users:
  - name: github-deployer-agent
    user:
      token: $TOKEN
contexts:
  - name: github-deployer-agent@homelab
    context: {cluster: homelab, user: github-deployer-agent, namespace: $NS}
current-context: github-deployer-agent@homelab
KCFG
