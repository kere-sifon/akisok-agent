# CI deploy pipeline (akisok-agent)

Runs on the `kere-sifon` org's self-hosted Actions runner, a pod inside the
homelab cluster (`runs-on: homelab-k8s`). GitHub-hosted runners cannot reach
Nexus or the cluster.

The runner image doesn't always include `kubectl`, so the **Ensure kubectl on
PATH** step uses one already on the runner (`PATH`, `/usr/local/bin`,
`/usr/bin`, or `~/bin`) or downloads kubectl v1.31.4 to `~/bin`.

## One-time setup (Mac, admin kubeconfig)

```bash
export KUBECONFIG="$HOME/homelab-k8s/kubeconfig"

deploy/deploy.sh secrets
kubectl apply -f deploy/ci/rbac.yaml
chmod +x deploy/ci/make-kubeconfig.sh
deploy/ci/make-kubeconfig.sh | gh secret set KUBE_CONFIG_B64 -R kere-sifon/akisok-agent
gh secret set NEXUS_PUSH_USER     -R kere-sifon/akisok-agent --body kere-docker
# Same docker-hosted-push password as kwesiblack / keresifonii:
gh secret set NEXUS_PUSH_PASSWORD -R kere-sifon/akisok-agent
```

`SYNC_SECRETS=0` in CI: app env, git SSH key, and `nexus-pull` stay Mac-managed.
