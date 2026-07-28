"""Le côté PyAirbyte du pont (S214) — exécuté par `/opt/pyairbyte/bin/python`, JAMAIS importé.

Ce fichier vit de l'autre côté d'une cloison. L'interpréteur qui le lance n'est pas celui
de l'API : il a `airbyte==0.53.2` et ses ~700 Mo de dépendances (pandas, pyarrow, duckdb,
starlette≥1.0…), tout ce qui est INCO-INSTALLABLE avec `fastapi==0.115.6`. D'où la
frontière, et d'où ce contrat, volontairement pauvre :

    stdin  ← un objet JSON : {"action": …, "connecteur": …, "config": {…}, …}
    stdout → une ligne JSON, et UNE SEULE : {"ok": true, …} ou {"ok": false, "erreur": …}
    stderr → tout le reste (logs PyAirbyte, barres de progression `rich`)

**Le piège qui a dicté ce design** : PyAirbyte écrit ses barres de progression `rich` et
ses résumés de sync sur *stdout*. Un protocole JSON sur stdout serait donc corrompu par la
librairie elle-même, de façon intermittente (selon que le terminal est un tty, selon la
durée de la sync). On duplique donc le vrai stdout AVANT tout import d'`airbyte`, puis on
branche le descripteur 1 sur stderr : à partir de là, tout ce que la librairie croit
imprimer « à l'écran » part dans les logs, et le canal du protocole reste propre par
construction. Vérifié par `test_pont.py::test_le_bruit_de_pyairbyte_ne_corrompt_pas_le_protocole`.

La configuration (identifiants tiers) arrive par **stdin**, jamais en argument : `ps` sur
l'hôte rendrait un jeton GitHub lisible par n'importe quel processus du conteneur.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ── Cloison stdout/stderr — AVANT tout import d'airbyte (cf. docstring) ──────
_CANAL = os.fdopen(os.dup(1), "w", encoding="utf-8")
os.dup2(2, 1)


def _repondre(charge: dict) -> None:
    _CANAL.write(json.dumps(charge, ensure_ascii=False, default=str) + "\n")
    _CANAL.flush()


def _etats_du_cache(cache, nom_source: str) -> dict:
    """{flux: curseur} tel que le cache le connaît après une lecture.

    C'est LA valeur que le sprint demande de « vérifier » : sans elle, l'incrémental est
    une promesse invérifiable. `stream_state_artifacts` est l'API publique du
    `StateProvider` (0.53.2) ; on ne lit pas la table `_airbyte_state` en direct pour ne
    pas dépendre d'un détail de schéma DuckDB.
    """
    fournisseur = cache.get_state_provider(nom_source)
    etats: dict[str, dict] = {}
    for artefact in fournisseur.stream_state_artifacts:
        etat = artefact.stream_state
        etats[artefact.stream_descriptor.name] = (
            etat.model_dump() if hasattr(etat, "model_dump") else dict(etat or {}))
    return etats


def _source(job: dict, racine: Path):
    import airbyte as ab
    return ab.get_source(
        job["connecteur"],
        config=job.get("config") or {},
        streams=job.get("flux") or "*",
        install_if_missing=True,
        # Les venvs de connecteur vivent sur le VOLUME, pas dans la couche image : c'est
        # ce qui évite de les réinstaller à chaque `up --build`.
        install_root=racine / "connecteurs",
    )


def _cache(job: dict, racine: Path):
    from airbyte.caches.duckdb import DuckDBCache
    return DuckDBCache(db_path=racine / "cache.duckdb", cache_dir=racine / "tmp",
                       # Un schéma par source : deux sources du même connecteur (deux
                       # dépôts GitHub) ne doivent pas mélanger leurs tables NI leurs états.
                       schema_name=job["schema"])


def action_verifier(job: dict, racine: Path) -> dict:
    source = _source(job, racine)
    source.check()
    return {"ok": True, "version_connecteur": source.connector_version}


def action_flux(job: dict, racine: Path) -> dict:
    source = _source(job, racine)
    return {"ok": True, "flux": sorted(source.get_available_streams())}


def action_sync(job: dict, racine: Path) -> dict:
    source = _source(job, racine)
    cache = _cache(job, racine)
    resultat = source.read(cache=cache, force_full_refresh=bool(job.get("complet")))
    return {
        "ok": True,
        "nb_enregistrements": resultat.processed_records,
        "flux": sorted(resultat.streams),
        "etats": _etats_du_cache(cache, job["connecteur"]),
    }


def action_etats(job: dict, racine: Path) -> dict:
    """Relit l'état SANS synchroniser — c'est ce qui permet de constater la reprise après
    une interruption : le curseur survivant est lisible avant même la sync suivante."""
    return {"ok": True, "etats": _etats_du_cache(_cache(job, racine), job["connecteur"])}


ACTIONS = {
    "verifier": action_verifier,
    "flux": action_flux,
    "sync": action_sync,
    "etats": action_etats,
}


def main() -> int:
    try:
        job = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as e:
        _repondre({"ok": False, "erreur": f"job illisible : {e}"})
        return 2
    action = ACTIONS.get(job.get("action"))
    if action is None:
        _repondre({"ok": False, "erreur": f"action inconnue : {job.get('action')!r}"})
        return 2
    racine = Path(job.get("racine") or os.getenv("CONNECTEURS_TRAVAIL", "/travail"))
    racine.mkdir(parents=True, exist_ok=True)
    try:
        _repondre(action(job, racine))
    except Exception as e:  # noqa: BLE001 — la frontière process rend TOUT échec en JSON
        # Le type est conservé : « ConnectorError: Config validation failed » dit à
        # l'opérateur où chercher, là où un « erreur » nu l'obligerait à ouvrir les logs.
        _repondre({"ok": False, "erreur": f"{type(e).__name__}: {e}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
