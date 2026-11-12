# akisok-agent on homelab-k8s. See deploy/k8s/README.md.
export KUBECONFIG ?= $(HOME)/homelab-k8s/kubeconfig
NS := akisok

.PHONY: deploy build apply secrets status logs rollback restart uninstall-mac-cron

deploy:
	@deploy/deploy.sh all

build:
	@deploy/deploy.sh build

apply:
	@deploy/deploy.sh apply

secrets:
	@deploy/deploy.sh secrets

status:
	@kubectl -n $(NS) get deploy,pods,svc,cronjob -o wide

logs:
	@kubectl -n $(NS) logs -f deploy/akisok-admin

rollback:
	@kubectl -n $(NS) rollout undo deploy/akisok-admin && kubectl -n $(NS) rollout status deploy/akisok-admin

restart:
	@kubectl -n $(NS) rollout restart deploy/akisok-admin

uninstall-mac-cron:
	@scripts/uninstall_pipeline_schedule.sh
