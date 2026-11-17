SHELL := /bin/bash
.DEFAULT_GOAL := help

ifeq ($(origin VPN),undefined)
VPN := $(if $(shell docker ps -aq --filter label=com.docker.compose.project=libre-box --filter label=com.docker.compose.service=vpn 2>/dev/null),1)
endif
export VPN

COMPOSE = docker compose$(if $(filter 1,$(VPN)), -f docker-compose.yml -f docker-compose.vpn.yml)

DOMAIN ?= $(or $(shell sed -n 's/^[[:space:]]*DOMAIN[[:space:]]*=[[:space:]]*//p' .env 2>/dev/null | tail -n 1 | tr -d "\"'\r"),localhost)
TAIL ?= 200
BACKUP_DIR ?= backups

HELP_WIDTH := 24
CONFIG_MOUNT_SERVICES := nginx librechat filebrowser
BACKUP_CONFIG_FILES := .env nginx/certs/fullchain.pem nginx/certs/privkey.pem vpn/wg0.conf
SHA256 := $(if $(shell command -v sha256sum 2>/dev/null),sha256sum,shasum -a 256)

COMPOSE_PROJECT = $$($(COMPOSE) config | sed -n '1s/^name: //p')
LIBRECHAT_IMAGE = $$($(COMPOSE) config --images librechat | grep -vxF "$$($(COMPOSE) config --images mongodb)")

MONGO_DATABASE := LibreChat
MONGO_SHELL_AUTH = db.getSiblingDB("admin").auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)
MONGO_TOOLS_AUTH = --username "$$MONGO_INITDB_ROOT_USERNAME" --authenticationDatabase admin --config <(printf "password: \"%s\"\n" "$$MONGO_INITDB_ROOT_PASSWORD")

ARCHIVE_RUN := docker run --rm --init --log-driver none --network none
PROJECT_VOLUME = project_volume() { if ! docker volume inspect "$${project}_$$1" > /dev/null 2>&1; then docker volume create --label com.docker.compose.project="$$project" --label com.docker.compose.volume="$$1" "$${project}_$$1" > /dev/null || return 1; fi; echo "$${project}_$$1"; }
WAIT_JOB = wait_job() { if [ -n "$$1" ] && ! wait "$$1"; then failed="$$failed$${failed:+, }$$2"; fi; }
STOP_JOBS = if [ -n "$$(jobs -pr)" ]; then kill $$(jobs -pr) 2> /dev/null || true; wait 2> /dev/null || true; fi

missing_args = $(strip $(foreach arg,$(1),$(if $(and $(filter command line,$(origin $(arg))),$(strip $($(arg)))),,$(arg))))

.PHONY: help up up-vpn down restart restart-all build reload rebuild update init-env env-check init-dirs certs cert-issue vpn-check ps logs \
        sandbox-build-core sandbox-build-standard sandbox-build-full sandbox-update sandbox-shell sandbox-reset mcp-shell \
        create-user list-users reset-password backup restore vpn-status data-size clear-logs clean

help: ## Show this help
	@printf "\033[1mLibreBox — available targets:\033[0m\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_%-]+:.*?## / {printf "  \033[36m%-$(HELP_WIDTH)s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\n\033[1mVariables:\033[0m\n"
	@printf "  \033[36m%-$(HELP_WIDTH)s\033[0m %s\n" "VPN=1|0" "Force the VPN overlay on or off (auto-detected from an existing vpn container)"
	@printf "  \033[36m%-$(HELP_WIDTH)s\033[0m %s\n" "TAIL=200|all" "Number of past log lines shown by logs and logs-<svc>"
	@printf "  \033[36m%-$(HELP_WIDTH)s\033[0m %s\n" "BACKUP_DIR=backups" "Directory that backup writes into"

up: ## Start the stack
	$(MAKE) env-check
	$(MAKE) init-dirs
	$(MAKE) certs
	$(MAKE) vpn-check
	$(COMPOSE) up -d

up-vpn: ## Start the stack with the VPN overlay
	@$(MAKE) up VPN=1

down: ## Stop and remove containers
	$(COMPOSE) --profile certbot down --remove-orphans

restart: ## Apply .env, compose and mounted config changes while keeping the sandbox and its jobs
	$(MAKE) vpn-check
	$(COMPOSE) up -d
	$(COMPOSE) restart $(CONFIG_MOUNT_SERVICES)

restart-all: ## Restart every service, including the sandbox (drops running jobs)
	$(MAKE) vpn-check
	$(COMPOSE) up -d
	$(COMPOSE) restart

build: ## Build local images
	$(COMPOSE) build

reload: ## Rebuild changed images and recreate services
	$(MAKE) init-dirs
	$(MAKE) certs
	$(MAKE) vpn-check
	$(COMPOSE) build
	$(COMPOSE) up -d

rebuild: ## Clean rebuild (build --no-cache --pull, then down + up)
	$(MAKE) vpn-check
	$(COMPOSE) build --no-cache --pull
	$(MAKE) init-dirs
	$(MAKE) certs
	$(COMPOSE) --profile certbot down
	$(COMPOSE) up -d

update: ## Pull newer upstream images, rebuild on fresh base images with the latest sandbox tools and recreate
	$(MAKE) init-dirs
	$(MAKE) certs
	$(MAKE) vpn-check
	@date +%s > services/sandbox/config/versions-refresh
	$(COMPOSE) pull --ignore-buildable
	$(COMPOSE) build --pull
	$(COMPOSE) up -d

init-env: ## Create .env from .env.example and generate the internal secrets that are still REPLACE_WITH_ placeholders
	@set -euo pipefail; \
	umask 077; \
	if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
	fi; \
	temporary=$$(mktemp .env.XXXXXX); \
	trap 'rm -f "$$temporary"' EXIT; \
	generated=""; \
	while IFS= read -r line || [ -n "$$line" ]; do \
		case "$$line" in \
			MONGODB_PASSWORD=REPLACE_WITH_*|JWT_SECRET=REPLACE_WITH_*|JWT_REFRESH_SECRET=REPLACE_WITH_*|CREDS_KEY=REPLACE_WITH_*|CREDS_IV=REPLACE_WITH_*|ADMIN_PANEL_SESSION_SECRET=REPLACE_WITH_*) \
				key="$${line%%=*}"; \
				if [ "$$key" = CREDS_IV ]; then bytes=16; else bytes=32; fi; \
				line="$$key=$$(openssl rand -hex $$bytes)"; \
				generated="$$generated $$key" ;; \
		esac; \
		printf '%s\n' "$$line" >> "$$temporary"; \
	done < .env; \
	if [ -n "$$generated" ]; then \
		mv "$$temporary" .env; \
		echo "Generated secrets in .env:$$generated"; \
	else \
		echo "No internal secret placeholders left in .env, nothing to generate"; \
	fi; \
	pending=$$(sed -n 's/^\([A-Z][A-Z0-9_]*\)=REPLACE_WITH_.*/\1/p' .env | tr '\n' ' '); \
	if [ -n "$$pending" ]; then \
		echo "Fill in manually in .env: $$pending"; \
	fi

env-check: ## Verify .env exists and has no REPLACE_WITH_ placeholders left
	@if [ ! -f .env ]; then \
		echo ".env is missing, run make init-env and fill in the values it lists before starting the stack" >&2; \
		exit 1; \
	fi; \
	pending=$$(sed -n 's/^\([A-Z][A-Z0-9_]*\)=REPLACE_WITH_.*/\1/p' .env | tr '\n' ' '); \
	if [ -n "$$pending" ]; then \
		echo "Placeholders are still left in .env: $$pending" >&2; \
		echo "Run make init-env and fill in the values it lists. MongoDB creates its root user only on the first start, so a start with empty or placeholder credentials can only be undone with make clean CONFIRM=yes" >&2; \
		exit 1; \
	fi

init-dirs: ## Create host bind-mount directories
	@mkdir -p data logs/librechat logs/nginx logs/mcp logs/auth-gate
	@chown 1000:1000 logs/librechat 2>/dev/null || chmod 0777 logs/librechat 2>/dev/null || true
	@chown 10001:10001 logs/auth-gate 2>/dev/null || chmod 0777 logs/auth-gate 2>/dev/null || true

certs: ## Generate a self-signed TLS cert for DOMAIN (skips if present)
	@if [ -f nginx/certs/fullchain.pem ] && [ -f nginx/certs/privkey.pem ]; then \
		echo "TLS cert already present in nginx/certs/, remove both files to regenerate it for $(DOMAIN)"; \
	else \
		domain="$(DOMAIN)"; \
		san="DNS:localhost,DNS:*.localhost,IP:127.0.0.1"; \
		case "$$domain" in \
			localhost|127.0.0.1) ;; \
			*[!0-9.]*) san="DNS:$$domain,$$san" ;; \
			*) san="IP:$$domain,$$san" ;; \
		esac; \
		echo "Generating self-signed TLS cert for $$domain in nginx/certs/"; \
		MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes -keyout nginx/certs/privkey.pem -out nginx/certs/fullchain.pem -subj "/CN=$$domain" -addext "subjectAltName=$$san"; \
	fi

cert-issue: ## Get a Let's Encrypt cert for DOMAIN over HTTP-01 and start auto-renewal (EMAIL=, DRY_RUN=1 only tests against staging)
	@set -euo pipefail; \
	if [ -n "$(call missing_args,EMAIL)" ]; then \
		echo "Missing EMAIL. Usage: make cert-issue EMAIL=me@example.com [DRY_RUN=1]" >&2; \
		exit 1; \
	fi; \
	if [ -z "$$($(COMPOSE) ps -q --status running nginx)" ]; then \
		echo "nginx is not running, so Let's Encrypt cannot reach the challenge. Start the stack with make up first" >&2; \
		exit 1; \
	fi; \
	dry_run=0; \
	if [ "$(origin DRY_RUN)" = "command line" ] && [ "$(DRY_RUN)" = 1 ]; then dry_run=1; fi; \
	$(COMPOSE) --profile certbot run --rm --no-deps -T -e CERTBOT_EMAIL="$$EMAIL" -e CERTBOT_DRY_RUN="$$dry_run" certbot issue; \
	if [ "$$dry_run" = 1 ]; then \
		echo "Nothing was saved, rerun without DRY_RUN=1 to get the real certificate"; \
		exit 0; \
	fi; \
	$(COMPOSE) exec -T nginx nginx -s reload; \
	$(COMPOSE) --profile certbot up -d certbot; \
	if ! grep -qE '^[[:space:]]*COMPOSE_PROFILES[[:space:]]*=' .env 2>/dev/null; then \
		if [ -s .env ] && [ -n "$$(tail -c 1 .env)" ]; then printf '\n' >> .env; fi; \
		echo "COMPOSE_PROFILES=certbot" >> .env; \
		echo "Added COMPOSE_PROFILES=certbot to .env, so make up keeps the renewal service running"; \
	elif ! grep -qE '^[[:space:]]*COMPOSE_PROFILES[[:space:]]*=.*certbot' .env; then \
		echo "Add certbot to COMPOSE_PROFILES in .env, otherwise make up will not keep the renewal service running" >&2; \
	fi; \
	echo "Certificate for $(DOMAIN) is installed, certbot checks for renewal every 12 hours and nginx reloads on its own"

vpn-check: ## Verify the VPN overlay files exist when the overlay is in use
	@$(COMPOSE) config -q || { echo "docker compose config failed, fix the error above before starting the stack" >&2; exit 1; }
	@services=$$($(COMPOSE) config --services); \
	if grep -qx vpn <<< "$$services"; then \
		for required in vpn/wg0.conf vpn/post-rules.txt; do \
			if [ ! -f "$$required" ]; then \
				echo "The VPN overlay is enabled but $$required is missing or not a regular file, add it or run with VPN=0" >&2; \
				exit 1; \
			fi; \
		done; \
	fi

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Tail logs from all services (TAIL=200 by default)
	$(COMPOSE) logs -f --tail=$(TAIL)

logs-%: ## Tail logs for one service (e.g. make logs-mcp)
	$(COMPOSE) logs -f --tail=$(TAIL) $*

sandbox-build-core: ## Build the minimal sandbox image
	SANDBOX_TARGET=core $(COMPOSE) build sandbox

sandbox-build-standard: ## Build the standard sandbox image
	SANDBOX_TARGET=standard $(COMPOSE) build sandbox

sandbox-build-full: ## Build the full sandbox image
	SANDBOX_TARGET=full $(COMPOSE) build sandbox

sandbox-update: ## Update the sandbox tools to their latest releases (drops running jobs)
	@date +%s > services/sandbox/config/versions-refresh
	$(MAKE) vpn-check
	$(COMPOSE) build sandbox
	$(COMPOSE) up -d sandbox

sandbox-shell: ## Open a login shell inside the sandbox
	$(COMPOSE) exec sandbox bash -l

sandbox-reset: ## Reset the sandbox to a clean OS (keeps /root/data)
	$(COMPOSE) up -d --force-recreate sandbox

mcp-shell: ## Open a shell inside the MCP container
	$(COMPOSE) exec mcp /bin/sh

create-user: ## Create a LibreChat user without opening registration (EMAIL=, NAME=, USERNAME=, with the password prompted)
	@missing="$(call missing_args,EMAIL NAME USERNAME)"; \
	if [ -n "$$missing" ]; then \
		echo "Missing $$missing. Usage: make create-user EMAIL=me@example.com NAME=Mee USERNAME=mee" >&2; \
		exit 1; \
	fi; \
	if [ "$(origin PASSWORD)" = "command line" ]; then \
		password="$$PASSWORD"; \
	else \
		IFS= read -rsp "Password for $$EMAIL (leave blank to generate one): " password; \
		echo; \
	fi; \
	printf '%s\n' "$$password" | $(COMPOSE) exec -T librechat npm run --silent create-user -- "$$EMAIL" "$$NAME" "$$USERNAME" --email-verified=true

list-users: ## List LibreChat user accounts
	@$(COMPOSE) exec -T librechat npm run --silent list-users

reset-password: ## Set a new password for a LibreChat user (prompts for the email and password)
	@$(COMPOSE) exec librechat npm run --silent reset-password

backup: ## Back up all data, certs, vpn/wg0.conf and .env into BACKUP_DIR/libre-box-<timestamp>
	@set -euo pipefail; \
	umask 077; \
	target="$(BACKUP_DIR)/libre-box-$$(date +%Y%m%d-%H%M%S)"; \
	partial="$$target.partial"; \
	if [ -e "$$target" ] || [ -e "$$partial" ]; then \
		echo "$$target already exists, wait a second and retry" >&2; \
		exit 1; \
	fi; \
	mkdir -p "$$partial" data librechat/plugins librechat/skill; \
	started_mongodb=; \
	filebrowser_stopped=; \
	trap '$(STOP_JOBS); rm -rf "$$partial"; if [ -n "$$filebrowser_stopped" ]; then $(COMPOSE) start filebrowser; fi; if [ -n "$$started_mongodb" ]; then $(COMPOSE) stop mongodb; fi' EXIT; \
	if [ -z "$$($(COMPOSE) ps -q --status running mongodb)" ]; then \
		echo "Starting mongodb for the backup, it is stopped again afterwards"; \
		$(COMPOSE) up -d --wait --no-recreate mongodb; \
		started_mongodb=1; \
	fi; \
	project=$(COMPOSE_PROJECT); \
	mongodb_image=$$($(COMPOSE) config --images mongodb); \
	$(PROJECT_VOLUME); \
	$(WAIT_JOB); \
	archive() { \
		output="$$1"; \
		members="$$2"; \
		shift 2; \
		$(ARCHIVE_RUN) --user 0:0 "$$@" --entrypoint sh "$$mongodb_image" -c "tar --create --gzip --file=- --numeric-owner --ignore-failed-read --warning=no-file-changed --warning=no-file-removed -C /backup $$members; [ \$$? -le 1 ]" > "$$partial/$$output"; \
	}; \
	uploads_volume=$$(project_volume librechat_uploads); \
	images_volume=$$(project_volume librechat_images); \
	filebrowser_volume=$$(project_volume filebrowser_db); \
	certbot_volume=; \
	if docker volume inspect "$${project}_certbot_letsencrypt" > /dev/null 2>&1; then \
		certbot_volume="$${project}_certbot_letsencrypt"; \
	fi; \
	if [ -n "$$($(COMPOSE) ps -q --status running filebrowser)" ]; then \
		echo "Stopping FileBrowser while its database is copied"; \
		$(COMPOSE) stop filebrowser; \
		filebrowser_stopped=1; \
	fi; \
	echo "Dumping the $(MONGO_DATABASE) database and archiving LibreChat uploads and images, data/, librechat/plugins/, librechat/skill/, FileBrowser's database and the Let's Encrypt state in parallel"; \
	archive filebrowser.tar.gz . --volume "$$filebrowser_volume:/backup:ro" & filebrowser_job=$$!; \
	$(COMPOSE) exec -T mongodb bash -c 'mongodump --quiet $(MONGO_TOOLS_AUTH) --db $(MONGO_DATABASE) --archive --gzip' > "$$partial/mongo.archive.gz" & mongo_job=$$!; \
	archive librechat-files.tar.gz "uploads client/public/images" --volume "$$uploads_volume:/backup/uploads:ro" --volume "$$images_volume:/backup/client/public/images:ro" & files_job=$$!; \
	archive data.tar.gz data --volume ./data:/backup/data:ro & data_job=$$!; \
	archive plugins.tar.gz plugins --volume ./librechat/plugins:/backup/plugins:ro & plugins_job=$$!; \
	archive skills.tar.gz skill --volume ./librechat/skill:/backup/skill:ro & skills_job=$$!; \
	certbot_job=; \
	if [ -n "$$certbot_volume" ]; then \
		archive certbot.tar.gz letsencrypt --volume "$$certbot_volume:/backup/letsencrypt:ro" & certbot_job=$$!; \
	fi; \
	failed=; \
	wait_job "$$filebrowser_job" "FileBrowser's database"; \
	if [ -n "$$filebrowser_stopped" ]; then \
		$(COMPOSE) start filebrowser; \
		filebrowser_stopped=; \
	fi; \
	wait_job "$$mongo_job" "the $(MONGO_DATABASE) database"; \
	wait_job "$$files_job" "LibreChat uploads and images"; \
	wait_job "$$data_job" "data/"; \
	wait_job "$$plugins_job" "librechat/plugins/"; \
	wait_job "$$skills_job" "librechat/skill/"; \
	wait_job "$$certbot_job" "the Let's Encrypt state"; \
	if [ -n "$$failed" ]; then \
		echo "Backup failed while saving $$failed, see the errors above" >&2; \
		exit 1; \
	fi; \
	for file in $(BACKUP_CONFIG_FILES); do \
		if [ -f "$$file" ]; then \
			mkdir -p "$$partial/config/$$(dirname "$$file")"; \
			cp "$$file" "$$partial/config/$$file"; \
		fi; \
	done; \
	{ \
		echo "created_at=$$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
		echo "librechat_image=$(LIBRECHAT_IMAGE)"; \
		echo "mongodb_image=$$mongodb_image"; \
	} > "$$partial/manifest.env"; \
	(cd "$$partial" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | sort | xargs $(SHA256) > SHA256SUMS); \
	mv "$$partial" "$$target"; \
	echo "Backup written to $$target ($$(du -sh "$$target" | cut -f 1)). It contains the .env file with every secret, the TLS private key and the WireGuard config, so keep it private"

restore: ## Replace all data, certs and vpn/wg0.conf with a backup, .env stays (BACKUP=, DESTROYS DATA). Requires CONFIRM=yes
	@set -euo pipefail; \
	if [ -n "$(call missing_args,BACKUP)" ]; then \
		echo "Missing BACKUP. Usage: make restore BACKUP=$(BACKUP_DIR)/libre-box-YYYYmmdd-HHMMSS CONFIRM=yes" >&2; \
		exit 1; \
	fi; \
	backup="$(patsubst %/,%,$(BACKUP))"; \
	if [ "$(CONFIRM)" != "yes" ]; then \
		echo "Refusing without CONFIRM=yes: the $(MONGO_DATABASE) database, LibreChat uploads and images, the data workspace, the plugins, the skills, FileBrowser's database, the TLS certs, the Let's Encrypt state and vpn/wg0.conf would be replaced by $$backup"; \
		exit 1; \
	fi; \
	for file in SHA256SUMS manifest.env mongo.archive.gz librechat-files.tar.gz; do \
		if [ ! -f "$$backup/$$file" ]; then \
			echo "$$backup/$$file is missing. BACKUP must be a directory written by make backup" >&2; \
			exit 1; \
		fi; \
	done; \
	echo "Verifying the checksums in $$backup"; \
	(cd "$$backup" && $(SHA256) -c --quiet SHA256SUMS); \
	backup_image=$$(sed -n 's/^librechat_image=//p' "$$backup/manifest.env"); \
	current_image=$(LIBRECHAT_IMAGE); \
	if [ "$$backup_image" != "$$current_image" ]; then \
		echo "Warning: the backup was taken with $$backup_image and the stack now uses $$current_image. LibreChat migrates the data on start" >&2; \
	fi; \
	project=$(COMPOSE_PROJECT); \
	mongodb_image=$$($(COMPOSE) config --images mongodb); \
	$(PROJECT_VOLUME); \
	$(WAIT_JOB); \
	replace() { \
		input="$$1"; \
		cleared="$$2"; \
		shift 2; \
		$(ARCHIVE_RUN) -i "$$@" --entrypoint sh "$$mongodb_image" -c "find $$cleared -mindepth 1 -delete && tar --extract --gzip --file=- --numeric-owner -C /restore" < "$$backup/$$input"; \
	}; \
	uploads_volume=$$(project_volume librechat_uploads); \
	images_volume=$$(project_volume librechat_images); \
	filebrowser_volume=; \
	if [ -f "$$backup/filebrowser.tar.gz" ]; then \
		filebrowser_volume=$$(project_volume filebrowser_db); \
	fi; \
	certbot_volume=; \
	if [ -f "$$backup/certbot.tar.gz" ]; then \
		certbot_volume=$$(project_volume certbot_letsencrypt); \
	fi; \
	running=$$($(COMPOSE) --profile certbot ps --services --status running librechat auth-gate filebrowser certbot); \
	was_mongodb_running=$$($(COMPOSE) ps -q --status running mongodb); \
	trap '$(STOP_JOBS)' EXIT; \
	trap 'echo "Restoring $$backup failed, so librechat, auth-gate, filebrowser and certbot stay stopped. Fix the error above and rerun make restore" >&2' ERR; \
	echo "Stopping librechat, auth-gate, filebrowser and certbot"; \
	$(COMPOSE) --profile certbot stop librechat auth-gate filebrowser certbot; \
	$(COMPOSE) up -d --wait --no-recreate mongodb; \
	mkdir -p data librechat/plugins librechat/skill; \
	echo "Replacing the $(MONGO_DATABASE) database, LibreChat uploads and images and everything else the backup holds in parallel"; \
	{ \
		$(COMPOSE) exec -T mongodb mongosh --quiet --eval '$(MONGO_SHELL_AUTH); db.getSiblingDB("$(MONGO_DATABASE)").dropDatabase()' > /dev/null && \
		$(COMPOSE) exec -T mongodb bash -c 'mongorestore --quiet $(MONGO_TOOLS_AUTH) --nsInclude "$(MONGO_DATABASE).*" --archive --gzip --stopOnError' < "$$backup/mongo.archive.gz"; \
	} & mongo_job=$$!; \
	replace librechat-files.tar.gz "/restore/uploads /restore/client/public/images" --user 0:0 --volume "$$uploads_volume:/restore/uploads" --volume "$$images_volume:/restore/client/public/images" & files_job=$$!; \
	data_job=; \
	if [ -f "$$backup/data.tar.gz" ]; then \
		replace data.tar.gz /restore/data --user 0:0 --volume ./data:/restore/data & data_job=$$!; \
	else \
		echo "No data workspace in $$backup, so data/ stays as it is"; \
	fi; \
	plugins_job=; \
	if [ -f "$$backup/plugins.tar.gz" ]; then \
		replace plugins.tar.gz /restore/plugins --user "$$(id -u):$$(id -g)" --volume ./librechat/plugins:/restore/plugins & plugins_job=$$!; \
	else \
		echo "No plugins in $$backup, so librechat/plugins/ stays as it is"; \
	fi; \
	skills_job=; \
	if [ -f "$$backup/skills.tar.gz" ]; then \
		replace skills.tar.gz /restore/skill --user "$$(id -u):$$(id -g)" --volume ./librechat/skill:/restore/skill & skills_job=$$!; \
	else \
		echo "No skills in $$backup, so librechat/skill/ stays as it is"; \
	fi; \
	filebrowser_job=; \
	if [ -n "$$filebrowser_volume" ]; then \
		replace filebrowser.tar.gz /restore --user 0:0 --volume "$$filebrowser_volume:/restore" & filebrowser_job=$$!; \
	else \
		echo "No FileBrowser database in $$backup, so it stays as it is"; \
	fi; \
	certbot_job=; \
	if [ -n "$$certbot_volume" ]; then \
		replace certbot.tar.gz /restore/letsencrypt --user 0:0 --volume "$$certbot_volume:/restore/letsencrypt" & certbot_job=$$!; \
	else \
		echo "No Let's Encrypt state in $$backup, so it stays as it is"; \
	fi; \
	failed=; \
	wait_job "$$mongo_job" "the $(MONGO_DATABASE) database"; \
	wait_job "$$files_job" "LibreChat uploads and images"; \
	wait_job "$$data_job" "data/"; \
	wait_job "$$plugins_job" "librechat/plugins/"; \
	wait_job "$$skills_job" "librechat/skill/"; \
	wait_job "$$filebrowser_job" "FileBrowser's database"; \
	wait_job "$$certbot_job" "the Let's Encrypt state"; \
	if [ -n "$$failed" ]; then \
		echo "Restoring $$backup failed while replacing $$failed, so librechat, auth-gate, filebrowser and certbot stay stopped. Fix the errors above and rerun make restore" >&2; \
		exit 1; \
	fi; \
	if [ -f "$$backup/config/nginx/certs/fullchain.pem" ] && [ -f "$$backup/config/nginx/certs/privkey.pem" ]; then \
		echo "Replacing the TLS certs in nginx/certs/, run make restart afterwards so nginx loads them"; \
		mkdir -p nginx/certs; \
		install -m 644 "$$backup/config/nginx/certs/fullchain.pem" nginx/certs/fullchain.pem; \
		install -m 600 "$$backup/config/nginx/certs/privkey.pem" nginx/certs/privkey.pem; \
	else \
		echo "No TLS certs in $$backup, so nginx/certs/ stays as it is"; \
	fi; \
	if [ -f "$$backup/config/vpn/wg0.conf" ]; then \
		echo "Replacing vpn/wg0.conf"; \
		mkdir -p vpn; \
		install -m 600 "$$backup/config/vpn/wg0.conf" vpn/wg0.conf; \
	else \
		echo "No vpn/wg0.conf in $$backup, so vpn/ stays as it is"; \
	fi; \
	trap - ERR; \
	if [ -f .env ] && [ -f "$$backup/config/.env" ]; then \
		for key in CREDS_KEY CREDS_IV; do \
			saved=$$(sed -n "s/^[[:space:]]*$$key[[:space:]]*=[[:space:]]*//p" "$$backup/config/.env" | head -n 1 | tr -d "\"'\r"); \
			current=$$(sed -n "s/^[[:space:]]*$$key[[:space:]]*=[[:space:]]*//p" .env | tail -n 1 | tr -d "\"'\r"); \
			if [ -n "$$saved" ] && [ "$$saved" != "$$current" ]; then \
				echo "Warning: $$key in .env differs from the backup, so the API keys and MCP credentials stored by users cannot be decrypted. Copy it from $$backup/config/.env and run make restart" >&2; \
			fi; \
		done; \
	fi; \
	if [ -n "$$running" ]; then \
		$(COMPOSE) --profile certbot start $$running; \
		echo "Restored $$backup"; \
	else \
		if [ -z "$$was_mongodb_running" ]; then \
			$(COMPOSE) stop mongodb; \
		fi; \
		echo "Restored $$backup. Start the stack with make up"; \
	fi

vpn-status: ## Show the sandbox public egress IP (through VPN if enabled)
	$(COMPOSE) exec sandbox bash -lc 'curl -s https://ifconfig.me; echo'

data-size: ## Show the size of the shared data workspace
	@du -sh data 2>/dev/null || echo "data/ is empty"

clear-logs: ## Clear the host log files under logs/ (deletes them when the stack is down)
	@if [ ! -d logs ]; then \
		echo "No logs/ directory to clear"; \
	elif running=$$($(COMPOSE) ps -q --status running 2>/dev/null) && [ -z "$$running" ]; then \
		find logs -type f ! -name .gitkeep -delete 2>/dev/null; \
		if [ -z "$$(find logs -type f ! -name .gitkeep 2>/dev/null)" ]; then \
			echo "Removed host log files under logs/"; \
		else \
			echo "Some files under logs/ could not be removed, retry with sudo"; \
			exit 1; \
		fi; \
	elif find logs -type f ! -name .gitkeep -exec truncate -s 0 {} + 2>/dev/null; then \
		echo "Truncated host log files under logs/, the files stay in place"; \
	else \
		echo "Some files under logs/ are not writable, retry with sudo"; \
		exit 1; \
	fi

clean: ## Remove containers AND volumes (DESTROYS DATA). Requires CONFIRM=yes
	@[ "$(CONFIRM)" = "yes" ] || { echo "Refusing without CONFIRM=yes"; exit 1; }
	$(COMPOSE) --profile certbot down -v --remove-orphans