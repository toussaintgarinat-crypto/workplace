# Filet de tests du monorepo Workplace (S116).
# `make test` = smoke santé des briques + suite du Cœur ; déterministe partout où les
# dépendances du Cœur existent. `make test-briques` = best-effort sur chaque brique.

.PHONY: help test smoke test-core test-cov test-briques test-all deps-audit

# Secrets factices requis par l'import du Cœur (coffre, Gateway) en contexte de test.
TEST_ENV = VAULT_SECRET=test-secret-0123456789 GATEWAY_KEY=test
PYTEST ?= python3 -m pytest

help:
	@echo "Cibles de test :"
	@echo "  make smoke         - contrat des manifests de briques (hors-ligne, rapide)"
	@echo "  make test-core     - suite pytest du Coeur (core/)"
	@echo "  make test          - smoke + test-core (le filet deterministe)"
	@echo "  make test-cov      - test-core avec couverture (pytest-cov)"
	@echo "  make test-briques  - pytest de chaque brique (best-effort)"
	@echo "  make test-all      - test + test-briques"
	@echo "  make deps-audit    - ecart des requirements vs constraints-workplace.txt"

smoke:
	$(PYTEST) tests

test-core:
	$(TEST_ENV) $(PYTEST) core

test: smoke test-core

test-cov:
	$(TEST_ENV) $(PYTEST) core --cov=core --cov-report=term-missing

test-briques:
	@echo "=== Tests par brique (best-effort, continue sur erreur) ==="
	@for d in briques/*/; do \
	  if ls $$d/test_*.py >/dev/null 2>&1; then \
	    echo "--- $$d ---"; \
	    ( cd $$d && $(TEST_ENV) python3 -m pytest -q ) || echo "  [ECHEC ou deps manquantes] $$d"; \
	  fi; \
	done

test-all: test test-briques

deps-audit:
	python3 scripts/audit_deps.py
