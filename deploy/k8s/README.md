# Deploying akisok-agent to homelab-k8s

Python image used for:

- **Admin UI** Deployment (`akisok-admin`) at http://192.168.2.245:8001
- **Pipeline** CronJob (`akisok-pipeline`) at 08:00 America/Toronto

Shares the `akisok` namespace with the public site. Approve still git-pushes MDX to
`kere-sifon/akisok-site`; the site deploy workflow rebuilds the Next image.

Public hostname: https://akisok-admin.keresifon.com — put **Cloudflare Access** in
front (the app has no login).

## Secrets (Mac, admin kubeconfig)

```bash
export KUBECONFIG="$HOME/homelab-k8s/kubeconfig"

# 1. GitHub has deploy keys disabled on kere-sifon/akisok-site. Put a fine-grained
#    PAT (Contents: Read and write on that repo only) in .env as GIT_TOKEN, then:
make secrets
# Optional SSH fallback if deploy keys are enabled later:
#   mkdir -p "$HOME/.config/akisok"
#   ssh-keygen -t ed25519 -f "$HOME/.config/akisok/id_ed25519" -N "" -C "akisok-admin-homelab"
```

`.env` must include Mongo, Tavily, AWS keys, Cloudinary, and can keep
`CONTENT_REPO_PATH=/content/akisok-site` (the entrypoint clones there).

## Deploy

```bash
make deploy
curl -I http://192.168.2.245:8001/
```

## Cutover from the Mac LaunchAgent

1. Confirm a CronJob ran: `kubectl -n akisok get cronjob,jobs`
2. `make uninstall-mac-cron`
3. Cloudflare Tunnel hostname `akisok-admin.keresifon.com` → `http://192.168.2.245:8001`
4. Zero Trust Access application for that hostname (allow your email)

Still needed before the first admin/pipeline image rolls out:

- `GIT_TOKEN` in `.env` (fine-grained PAT, Contents write on `kere-sifon/akisok-site`), then `make secrets`
- `gh secret set NEXUS_PUSH_PASSWORD -R kere-sifon/akisok-agent`
- Push `main` on `kere-sifon/akisok-agent` so gh-runner-02 builds the image
- After a CronJob succeeds: `make uninstall-mac-cron`
