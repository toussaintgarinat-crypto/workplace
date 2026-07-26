# roomkit-visio — SIP infrastructure for the meet platform
#
# Common dev commands:
#   make bootstrap        first-time setup: .env + TLS certs + image pull
#   make start            bring up the SIP stack (no monitoring)
#   make start-all        bring up SIP stack + prometheus/grafana/loki/promtail/exporters
#   make stop             stop containers (keep state)
#   make down             stop + remove containers (keep volumes)
#   make destroy          stop + remove containers + drop volumes (resets postgres)
#   make logs SVC=kamailio
#   make status
#   make psql             open psql in the kamailio db
#   make reload           kamcmd address + dispatcher reload

SHELL := /bin/bash

# ============================================================
# Variables
# ============================================================

BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[1;32m
YELL  := \033[1;33m

PROJECT       := roomkit-visio
COMPOSE       := docker compose
COMPOSE_MON   := docker compose --profile monitoring

# Outbound LAN IP from the default route; fallback if detection fails.
DETECTED_IP   := $(shell ip -4 route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+' | head -1)
LAN_IP        := $(if $(DETECTED_IP),$(DETECTED_IP),192.168.0.10)

CERT_DIR      := certs
CERT_CRT      := $(CERT_DIR)/tls.crt
CERT_KEY      := $(CERT_DIR)/tls.key
# Source of meet's TLS certs. Override with: MEET_CERTS=/your/path make certs
MEET_CERTS    ?= ../meet/certs

# livekit-sip source. Override with: LIVEKIT_SIP_SRC=/your/path make sip-build
LIVEKIT_SIP_SRC       ?= ../livekit-sip
LIVEKIT_SIP_LOCAL_TAG := livekit-sip:local

# ============================================================
# Targets
# ============================================================

.DEFAULT_GOAL := help

help: ## list available targets
	@echo -e "$(BOLD)$(PROJECT) Makefile$(RESET)"
	@echo -e "Detected LAN IP: $(GREEN)$(LAN_IP)$(RESET)"
	@echo
	@echo -e "Usage: $(BOLD)make <target>$(RESET)"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-16s$(RESET) %s\n", $$1, $$2}'
.PHONY: help

# ---- bootstrap / init ----

bootstrap: ## first-time setup: write .env, ensure TLS certs, build livekit-sip, pre-pull other images
bootstrap: env certs sip-build pull
	@echo -e "$(GREEN)Bootstrap complete.$(RESET) Run '$(BOLD)make start$(RESET)' (or '$(BOLD)make start-all$(RESET)' for monitoring)."
.PHONY: bootstrap

env: .env ## create .env from .env.example with auto-detected LAN IP
.PHONY: env

.env:
	@echo -e "$(BOLD)Writing .env (MY_IP_ADDR=$(LAN_IP))$(RESET)"
	@sed 's/^MY_IP_ADDR=.*/MY_IP_ADDR=$(LAN_IP)/' .env.example > .env
	@cat .env

certs: $(CERT_CRT) $(CERT_KEY) ## ensure TLS certs exist (copy from meet, else self-sign)
.PHONY: certs

$(CERT_CRT) $(CERT_KEY):
	@mkdir -p $(CERT_DIR)
	@if [ -f "$(MEET_CERTS)/tls.crt" ] && [ -f "$(MEET_CERTS)/tls.key" ]; then \
	  echo -e "$(BOLD)Copying TLS certs from $(MEET_CERTS)$(RESET)"; \
	  cp "$(MEET_CERTS)/tls.crt" "$(CERT_CRT)"; \
	  cp "$(MEET_CERTS)/tls.key" "$(CERT_KEY)"; \
	else \
	  echo -e "$(YELL)Meet certs not found at $(MEET_CERTS); generating self-signed for CN=$(LAN_IP)$(RESET)"; \
	  openssl req -x509 -newkey rsa:2048 -nodes \
	    -keyout "$(CERT_KEY)" -out "$(CERT_CRT)" \
	    -days 365 \
	    -subj "/CN=$(LAN_IP)" \
	    -addext "subjectAltName=IP:$(LAN_IP),DNS:localhost" \
	    >/dev/null 2>&1; \
	fi
	@chmod 600 "$(CERT_KEY)"
	@ls -la $(CERT_DIR)

certs-regen: ## delete existing certs and regenerate (self-signed only)
	@rm -f $(CERT_CRT) $(CERT_KEY)
	@$(MAKE) --no-print-directory certs MEET_CERTS=/dev/null
.PHONY: certs-regen

pull: ## pre-pull all docker images (skips livekit-sip:local)
	@echo -e "$(BOLD)Pulling images$(RESET)"
	@$(COMPOSE_MON) pull --ignore-pull-failures
.PHONY: pull

# ---- lifecycle ----

start: env certs ## bring up the SIP stack (no monitoring)
	@echo -e "$(BOLD)Starting SIP stack$(RESET)"
	@$(COMPOSE) up -d
	@$(COMPOSE) ps
.PHONY: start

start-all: env certs ## bring up the SIP stack + monitoring
	@echo -e "$(BOLD)Starting SIP stack + monitoring$(RESET)"
	@$(COMPOSE_MON) up -d
	@$(COMPOSE_MON) ps
.PHONY: start-all

stop: ## stop containers (keep state)
	@$(COMPOSE_MON) stop
.PHONY: stop

down: ## stop and remove containers (keep volumes)
	@$(COMPOSE_MON) down
.PHONY: down

destroy: ## stop + remove containers AND drop volumes (resets postgres)
	@echo -e "$(YELL)This will drop the kamailio postgres data volume.$(RESET)"
	@read -p "Continue? [y/N] " ans && [ "$$ans" = "y" ] || exit 1
	@$(COMPOSE_MON) down -v
.PHONY: destroy

restart: ## restart all containers
	@$(COMPOSE_MON) restart
.PHONY: restart

# ---- introspection ----

status: ## docker compose ps (including monitoring services if started)
	@$(COMPOSE_MON) ps
.PHONY: status

logs: ## follow logs; pass SVC=name to scope (e.g. make logs SVC=kamailio)
	@$(COMPOSE_MON) logs -f $(SVC)
.PHONY: logs

ports: ## list host ports owned by roomkit-visio containers
	@ss -tunlp 2>/dev/null | grep -E ':5060|:5061|:5080|:25432|:20301|:9190|:3001|:3100' || true
.PHONY: ports

# ---- ops shortcuts ----

psql: ## open psql in the kamailio db (interactive)
	@./bin/psql-kamailio.sh
.PHONY: psql

sql: ## run a one-shot query, e.g. make sql Q="SELECT * FROM dispatcher;"
	@./bin/psql-kamailio.sh -c "$(Q)"
.PHONY: sql

reload: ## kamcmd permissions.addressReload + dispatcher.reload
	@./bin/reload-kamailio.sh
.PHONY: reload

dispatcher: ## show kamailio dispatcher destinations
	@$(COMPOSE) exec kamailio kamcmd dispatcher.list
.PHONY: dispatcher

rtpengine-show: ## show kamailio's view of rtpengine peers
	@$(COMPOSE) exec kamailio kamcmd rtpengine.show all
.PHONY: rtpengine-show

# ---- GStreamer pipeline dumps ----

gst-clear: ## delete every .dot in ./gst-dots/
	@find gst-dots -type f -name '*.dot' -delete -print
.PHONY: gst-clear

# ---- livekit-sip build ----

sip-build: ## docker-build livekit-sip:local from $LIVEKIT_SIP_SRC (default: ../livekit-sip)
	@if [ ! -f "$(LIVEKIT_SIP_SRC)/build/sip/Dockerfile" ]; then \
	  echo "ERROR: $(LIVEKIT_SIP_SRC)/build/sip/Dockerfile not found"; \
	  echo "Set LIVEKIT_SIP_SRC=/path/to/livekit-sip to override."; \
	  exit 1; \
	fi
	@echo -e "$(BOLD)Building $(LIVEKIT_SIP_LOCAL_TAG) from $(LIVEKIT_SIP_SRC)$(RESET)"
	@docker build -f "$(LIVEKIT_SIP_SRC)/build/sip/Dockerfile" \
	  -t "$(LIVEKIT_SIP_LOCAL_TAG)" "$(LIVEKIT_SIP_SRC)"
.PHONY: sip-build

sip-rebuild: ## rebuild livekit-sip:local and force-recreate the running container
sip-rebuild: sip-build
	@$(COMPOSE) up -d --force-recreate livekit-sip
.PHONY: sip-rebuild

# ---- meta ----

show: ## print detected env values
	@echo "Detected LAN IP : $(LAN_IP)"
	@echo "Project         : $(PROJECT)"
	@echo "Meet certs path : $(MEET_CERTS)"
	@echo ".env exists     : $(if $(wildcard .env),yes,no)"
	@echo "TLS certs       : $(if $(wildcard $(CERT_CRT)),present,missing)"
.PHONY: show

clean: down ## stop containers and remove generated .env / certs
	@rm -f .env $(CERT_CRT) $(CERT_KEY)
	@echo -e "$(GREEN)Cleaned$(RESET)"
.PHONY: clean
