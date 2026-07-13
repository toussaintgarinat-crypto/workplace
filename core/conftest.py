"""Isolation des tests du Cœur — exécuté par pytest AVANT tout module de test (donc avant
que les modules applicatifs ne soient importés).

Pourquoi ce fichier existe. Beaucoup de modules du Cœur figent leur chemin de données À
L'IMPORT, p. ex. ::

    CONFIG_PATH = Path(os.getenv("ASSISTANT_CONFIG_PATH", "/data/assistant_config.json"))

Le défaut « /data » n'est inscriptible que DANS le conteneur. Hors conteneur (poste de dev,
`make test-core`), il est en lecture seule. Deux dégâts en découlaient, tous deux dus à
l'ORDRE d'import de la suite complète :

1. **Crash de collecte** : `test_langue.py` appelle `config_assistant.definir_langue()` au
   niveau module ; si un test antérieur a déjà importé `config_assistant` sans que la variable
   soit posée, `CONFIG_PATH` est figé sur « /data » et le `mkdir` lève `OSError` → toute la
   collecte s'arrête.
2. **62 échecs de pollution d'ordre** : `routers/assistant.py` importe `journal_conversations`
   (et d'autres) ; le premier test qui charge le Cœur fige leur chemin sur « /data ». Comme
   ces écritures sont best-effort (jamais bloquantes), elles échouent EN SILENCE → les tests
   qui relisent le fichier voient du vide et cassent, alors qu'ils passent en isolation.

La correction, faite ici une fois pour toutes : rediriger CHAQUE chemin de données du Cœur
vers un dossier temporaire de session, avant le premier import applicatif. Les fichiers de
test qui posaient déjà leur propre `mkdtemp` continuent de fonctionner (leur affectation est
soit reprise, soit sans effet mais inoffensive) ; surtout, plus aucun chemin ne tombe sur
« /data ». Les secrets factices requis à l'import (coffre, Gateway) sont fournis en
`setdefault` pour que `pytest core` tourne même sans passer par le Makefile.
"""
import os
import sys
import tempfile

import pytest

# Un seul dossier de session pour tous les chemins de données du Cœur.
_TMP = tempfile.mkdtemp(prefix="workplace-core-tests-")

# Chemins de données figés à l'import par les modules du Cœur : forcés vers le temp de session
# (nom → fichier). On FORCE (et non setdefault) car le but est qu'aucun ne pointe sur « /data »
# pendant les tests, quel que soit l'environnement d'appel.
_CHEMINS = {
    "ASSISTANT_CONFIG_PATH": "assistant_config.json",
    "AMELIORATION_PATH": "ameliorations.json",
    "CAPACITES_PROPOSEES_PATH": "capacites_proposees.json",
    "CONVERSATIONS_JOURNAL_PATH": "conversations_journal.jsonl",
    "HORLOGE_DB": "horloge.db",
    "IDENTITE_PATH": "identite.json",
    "LIVRAISONS_DB": "livraisons.db",
    "LLM_CACHE_PATH": "llm_cache.jsonl",
    "PROFIL_PATH": "profil.md",
    "PROJETS_PATH": "projets.json",
    "PROPRIOCEPTION_PATH": "proprioception.jsonl",
    "RAPPELS_DB": "rappels.db",
    "SHADOW_RUNS_PATH": "shadow_runs.jsonl",
    "USAGE_LLM_PATH": "usage_llm.jsonl",
    "GATEWAY_ENV_PATH": "gateway.env",
}
for _var, _fichier in _CHEMINS.items():
    os.environ[_var] = os.path.join(_TMP, _fichier)

# Secrets factices requis par l'import du Cœur (coffre, Gateway). `setdefault` : le Makefile
# (make test-core) les fournit déjà ; on ne les écrase donc pas, mais `pytest core` nu marche.
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")


# Points chauds de modules PARTAGÉS que les tests remplacent par des doublures (client httpx,
# pipeline LLM, chaîne de modèles, juge de proprioception). module → attributs.
_POINTS_CHAUDS = {
    "httpx": ("AsyncClient",),
    "llm_pipeline": ("completer",),
    "config_assistant": ("chaine_modeles", "lister_modeles"),
    "proprioception": ("_juger",),
    "agenda": ("lister_evenements",),
    "journal_usage": ("BUDGET_MOIS",),   # plafond budget mensuel : posé bas par les tests budget
}


@pytest.fixture(autouse=True)
def _isoler_globaux_partages():
    """Filet anti-pollution d'ordre, appliqué à CHAQUE test du Cœur.

    Beaucoup de tests simulent le réseau/LLM en remplaçant un attribut de module partagé
    (p. ex. `agenda.httpx.AsyncClient = _FakeClient`, `config_assistant.chaine_modeles = _mock`)
    et oublient de le restaurer. En suite complète, la doublure FUIT vers les tests suivants —
    un test reçoit le `_FakeClient` d'un autre, ou une chaîne de modèles mockée au lieu de la
    sienne. Plutôt que corriger chaque test, on photographie ces points chauds avant le test et
    on les rétablit après : l'attribut revient toujours à son état d'avant-test, que le test
    l'ait restauré lui-même ou non. On ne touche qu'aux modules DÉJÀ importés (sys.modules) —
    aucun import forcé, aucune dépendance nouvelle."""
    snapshot = []
    for nom_mod, attrs in _POINTS_CHAUDS.items():
        mod = sys.modules.get(nom_mod)
        if mod is None:
            continue
        for attr in attrs:
            if hasattr(mod, attr):
                snapshot.append((mod, attr, getattr(mod, attr)))
    try:
        yield
    finally:
        for mod, attr, valeur in snapshot:
            setattr(mod, attr, valeur)
