.PHONY: start stop logs reset sync

# `sync` AVANT `up` : la liste des modèles gratuits d'OpenRouter tourne vite (un modèle
# gratuit passe payant ou disparaît sans préavis, et litellm remonte alors des
# NotFoundError en boucle). Le script réécrit la section entre les marqueurs
# AUTO-FREE-MODELS-* de litellm_config.yaml ; il ne fait rien si OPENROUTER_API_KEY est
# absent. Sans ce câblage, sync_free_models.py restait orphelin — la liste avait figé
# 51 jours (06/06 → 27/07) avant qu'on ne le remarque dans les logs.
start: sync
	docker compose up -d

sync:
	@set -a; [ -f .env ] && . ./.env; set +a; python3 sync_free_models.py

stop:
	docker compose down

logs:
	docker compose logs -f

reset:
	docker compose down -v
