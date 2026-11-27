# S248 parties 1+2 — Contrat de données utilisateur + app pilote Studio — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Qu'une app déclare un `contrat_donnees` (exporter / réinitialiser / importer pour UN utilisateur), avec une bibliothèque de paquet signé, un test de conformité réutilisable, et le Studio comme première app conforme.

**Architecture :** Une bibliothèque stdlib `shared/contrat_donnees.py` (paquet tar.gz = `meta.json` signé HMAC + `donnees.json`, copiée dans chaque brique par `outils/sync_socle.sh`). Le Studio ajoute `support.py` (logique pure : export/reset/import/vérification sur fichiers JSON, paramétrée par une racine pour permettre la vérification en dossier jetable) et trois+une routes internes `/support/*` protégées par une clé DÉDIÉE `STUDIO_SUPPORT_KEY` (jamais la `STUDIO_KEY`). Le reset exige l'empreinte exacte des données courantes (= « le paquet couvre l'état actuel »).

**Tech Stack :** Python 3 stdlib (tarfile, hmac, hashlib, json), FastAPI (déjà dans le Studio), pytest.

**Hors de ce plan (partie 3, plan suivant) :** outils `livraison_*` côté assistant, chiffrement au repos + stockage SeaweedFS, rétention 14 jours, validation du bloc `contrat_donnees` par le Cœur, prérequis « paquet vérifié » dans les approbations, preuve LIVE (SLIVE). Les médias (images/audio) des séries vivent dans d'autres briques : hors paquet, limite à documenter.

## Global Constraints

- Les routes `/support/*` sont INTERNES : clé dédiée `STUDIO_SUPPORT_KEY` (header `X-Support-Key`), comparée en temps constant ; variable absente → 503 (fonction désactivée), jamais de repli ouvert. La `STUDIO_KEY` et les clés `API_KEYS` ne donnent AUCUN accès à `/support/*`.
- Le paquet n'est jamais lu par l'assistant : seuls `meta` (comptages, version, empreinte) sortent en en-têtes. Aucune donnée perso dans les messages d'erreur.
- Un paquet est refusé s'il est : illisible, falsifié (signature/somme de contrôle), d'une autre app, d'un autre utilisateur, ou d'une `version_schema` SUPÉRIEURE à celle de l'app. Version inférieure → migration par crochet, sinon refus.
- `importer` refuse tout objet dont l'identité n'est pas l'utilisateur ciblé, et tout identifiant en conflit avec l'objet d'un autre utilisateur, AVANT d'écrire quoi que ce soit.
- Identifiants d'objets : regex `^[A-Za-z0-9_-]{1,64}$` (anti traversée de chemin).
- Tests purs, aucun appel réseau. Le Studio reste « stdlib seulement » côté dépendances (pas de nouvelle ligne dans `requirements.txt`).
- Commits en français, un par tâche, terminés par les lignes d'attribution du système.

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `shared/contrat_donnees.py` (créer) | Source unique : paquet signé, empreinte, comptages, validation du bloc manifeste |
| `shared/test_contrat_donnees.py` (créer) | Tests de la bibliothèque |
| `shared/conformite_contrat.py` (créer) | Harnais de conformité réutilisable par toute app candidate |
| `briques/studio/contrat_donnees.py` (copie) | Copie poussée par `outils/sync_socle.sh` |
| `briques/studio/studio.py` (modifier) | `identite_effective` déplacée ici (réutilisée par `support.py`) |
| `briques/studio/support.py` (créer) | Export / reset / import / vérification des données d'un utilisateur |
| `briques/studio/main.py` (modifier) | Clé support + routes `/support/*` ; alias `_identite_effective` |
| `briques/studio/test_support.py` (créer) | Tests de `support.py` |
| `briques/studio/test_support_routes.py` (créer) | Tests des routes + conformité + mutation |
| `briques/studio/manifest.json` (modifier) | Bloc `contrat_donnees` |
| `outils/sync_socle.sh` (modifier) | Copie de `contrat_donnees.py` |
| `docs/GUIDE-contrat-donnees.md` (créer) | Guide pour les apps candidates |

---

### Task 1 : Bibliothèque du paquet signé

**Files :**
- Create : `shared/contrat_donnees.py`
- Test : `shared/test_contrat_donnees.py`

**Interfaces :**
- Produces :
  - `class PaquetInvalide(Exception)` avec attribut `.raison` ∈ {`illisible`, `trop_gros`, `format`, `signature`, `somme_controle`, `app`, `utilisateur`, `version_future`}
  - `empreinte(objets: dict) -> str` (sha256 hex du JSON canonique)
  - `comptages(objets: dict) -> dict[str, int]`
  - `construire_paquet(app: str, utilisateur: str, version_schema: str, objets: dict, cle: bytes, maintenant: datetime | None = None) -> bytes`
  - `lire_paquet(octets: bytes, cle: bytes, app: str, utilisateur: str, version_schema_app: str) -> tuple[dict, dict]` → `(meta, objets)`
  - `valider_bloc_contrat(bloc) -> list[str]` (liste d'erreurs, vide = conforme)

- [ ] **Step 1 : Écrire les tests qui échouent**

`shared/test_contrat_donnees.py` :

```python
import io
import json
import tarfile

import pytest

from shared import contrat_donnees as C

CLE = b"cle-de-test"
OBJETS = {"series": [{"id": "s1", "cree_par": "claire"}], "profils": []}


def _paquet(**kw):
    args = dict(app="studio", utilisateur="claire", version_schema="2", objets=OBJETS, cle=CLE)
    args.update(kw)
    return C.construire_paquet(**args)


def _tar(membres: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for nom, contenu in membres.items():
            info = tarfile.TarInfo(nom)
            info.size = len(contenu)
            t.addfile(info, io.BytesIO(contenu))
    return buf.getvalue()


def _membres(octets: bytes) -> dict:
    with tarfile.open(fileobj=io.BytesIO(octets), mode="r:gz") as t:
        return {m.name: t.extractfile(m).read() for m in t.getmembers()}


def _raison(octets, **kw):
    args = dict(cle=CLE, app="studio", utilisateur="claire", version_schema_app="2")
    args.update(kw)
    with pytest.raises(C.PaquetInvalide) as e:
        C.lire_paquet(octets, **args)
    return e.value.raison


def test_aller_retour():
    meta, objets = C.lire_paquet(_paquet(), CLE, "studio", "claire", "2")
    assert objets == OBJETS
    assert meta["comptages"] == {"profils": 0, "series": 1}
    assert meta["empreinte"] == C.empreinte(OBJETS)
    assert meta["version_schema"] == "2" and meta["utilisateur"] == "claire"


def test_empreinte_ne_depend_pas_de_l_ordre_des_cles():
    assert C.empreinte({"a": 1, "b": 2}) == C.empreinte({"b": 2, "a": 1})


def test_mauvaise_cle_refusee():
    assert _raison(_paquet(), cle=b"autre") == "signature"


def test_autre_utilisateur_refuse():
    assert _raison(_paquet(), utilisateur="marina") == "utilisateur"


def test_autre_app_refusee():
    assert _raison(_paquet(app="agenda")) == "app"


def test_version_future_refusee():
    assert _raison(_paquet(version_schema="3")) == "version_future"


def test_version_inferieure_acceptee_et_signalee():
    meta, _ = C.lire_paquet(_paquet(version_schema="1"), CLE, "studio", "claire", "2")
    assert meta["version_schema"] == "1"


def test_donnees_falsifiees_somme_de_controle():
    m = _membres(_paquet())
    m["donnees.json"] = json.dumps({"series": [], "profils": []}).encode()
    assert _raison(_tar(m)) == "somme_controle"


def test_meta_falsifiee_signature():
    m = _membres(_paquet())
    meta = json.loads(m["meta.json"])
    meta["utilisateur"] = "marina"
    m["meta.json"] = json.dumps(meta).encode()
    assert _raison(_tar(m), utilisateur="marina") == "signature"


def test_pas_une_archive():
    assert _raison(b"pas une archive") == "illisible"


def test_membre_inattendu_refuse():
    m = _membres(_paquet())
    m["../evil"] = b"x"
    assert _raison(_tar(m)) == "illisible"


def test_membre_manquant_refuse():
    m = _membres(_paquet())
    del m["donnees.json"]
    assert _raison(_tar(m)) == "illisible"


def test_octets_trop_gros(monkeypatch):
    monkeypatch.setattr(C, "TAILLE_MAX", 10)
    assert _raison(_paquet()) == "trop_gros"


def test_bloc_contrat_conforme():
    bloc = {"version_schema": "3",
            "exporter": {"methode": "POST", "chemin": "/support/exporter"},
            "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
            "importer": {"methode": "POST", "chemin": "/support/importer"}}
    assert C.valider_bloc_contrat(bloc) == []


@pytest.mark.parametrize("bloc", [
    None, {}, {"version_schema": "x"},
    {"version_schema": "1", "exporter": {"methode": "GET", "chemin": "/support/exporter"},
     "reinitialiser": {"methode": "POST", "chemin": "/support/r"},
     "importer": {"methode": "POST", "chemin": "/support/i"}},
    {"version_schema": "1", "exporter": {"methode": "POST", "chemin": "/public/exporter"},
     "reinitialiser": {"methode": "POST", "chemin": "/support/r"},
     "importer": {"methode": "POST", "chemin": "/support/i"}},
])
def test_bloc_contrat_non_conforme(bloc):
    assert C.valider_bloc_contrat(bloc) != []
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `cd /Users/garinat_t/Desktop/Workplace && python -m pytest shared/test_contrat_donnees.py -q`
Expected : erreur d'import (`cannot import name 'contrat_donnees'`).

- [ ] **Step 3 : Implémenter**

`shared/contrat_donnees.py` :

```python
"""Contrat d'app « données utilisateur » (S248) — bibliothèque partagée, stdlib seule.

Une app qui veut la portée « par utilisateur » déclare un bloc `contrat_donnees` dans son
manifeste et expose trois routes internes (exporter / réinitialiser / importer). Ce module
fournit le PAQUET échangé : une archive tar.gz de deux membres,
  • `meta.json`    : app, utilisateur, version_schema, date, comptages par type, empreinte
                     des données, signature HMAC-SHA256 de tout le reste ;
  • `donnees.json` : les données de CET utilisateur, JSON canonique.
L'assistant ne manipule que `meta` (jamais `donnees`). Source unique = `shared/` ; copiée dans
chaque brique par `outils/sync_socle.sh` (chaque brique est une image autonome).
"""
import hashlib
import hmac
import io
import json
import tarfile
import zlib
from datetime import datetime, timezone
from typing import Optional

FORMAT = 1
TAILLE_MAX = 64 * 1024 * 1024
MEMBRES = ("meta.json", "donnees.json")
ACTIONS = ("exporter", "reinitialiser", "importer")


class PaquetInvalide(Exception):
    def __init__(self, raison: str, detail: str = ""):
        super().__init__(f"{raison} : {detail}" if detail else raison)
        self.raison = raison


def _canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def empreinte(objets: dict) -> str:
    return hashlib.sha256(_canon(objets)).hexdigest()


def comptages(objets: dict) -> dict:
    return {k: len(v) for k, v in sorted(objets.items())}


def _signer(meta_sans_signature: dict, cle: bytes) -> str:
    return hmac.new(cle, _canon(meta_sans_signature), hashlib.sha256).hexdigest()


def _version(v) -> int:
    try:
        n = int(str(v))
    except ValueError:
        raise PaquetInvalide("format", "version_schema non numérique")
    if n < 0:
        raise PaquetInvalide("format", "version_schema négative")
    return n


def construire_paquet(app: str, utilisateur: str, version_schema: str, objets: dict,
                      cle: bytes, maintenant: Optional[datetime] = None) -> bytes:
    donnees = _canon(objets)
    meta = {
        "format": FORMAT, "app": app, "utilisateur": utilisateur,
        "version_schema": str(version_schema),
        "cree_le": (maintenant or datetime.now(timezone.utc)).isoformat(),
        "comptages": comptages(objets),
        "empreinte": hashlib.sha256(donnees).hexdigest(),
    }
    meta["signature"] = _signer(meta, cle)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for nom, contenu in (("meta.json", _canon(meta)), ("donnees.json", donnees)):
            info = tarfile.TarInfo(nom)
            info.size = len(contenu)
            t.addfile(info, io.BytesIO(contenu))
    return buf.getvalue()


def _lire_membres(octets: bytes) -> dict:
    if len(octets) > TAILLE_MAX:
        raise PaquetInvalide("trop_gros")
    out: dict = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(octets), mode="r:gz") as t:
            for m in t:   # taille vérifiée AVANT de décompresser le membre (anti bombe)
                if m.name not in MEMBRES or not m.isfile() or m.name in out:
                    raise PaquetInvalide("illisible", "contenu inattendu")
                if m.size > TAILLE_MAX:
                    raise PaquetInvalide("trop_gros")
                out[m.name] = t.extractfile(m).read()
    except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
        raise PaquetInvalide("illisible", type(e).__name__) from e
    if set(out) != set(MEMBRES):
        raise PaquetInvalide("illisible", "membre manquant")
    return out


def lire_paquet(octets: bytes, cle: bytes, app: str, utilisateur: str,
                version_schema_app: str) -> tuple:
    """Vérifie (dans cet ordre) lisibilité, signature, somme de contrôle, app, utilisateur,
    version. Renvoie `(meta, objets)` ou lève `PaquetInvalide`."""
    membres = _lire_membres(octets)
    try:
        meta = json.loads(membres["meta.json"])
        if not isinstance(meta, dict):
            raise ValueError
    except ValueError:
        raise PaquetInvalide("illisible", "meta.json")
    signature = meta.pop("signature", "")
    if not isinstance(signature, str) or not hmac.compare_digest(signature, _signer(meta, cle)):
        raise PaquetInvalide("signature")
    if meta.get("format") != FORMAT:
        raise PaquetInvalide("format")
    if hashlib.sha256(membres["donnees.json"]).hexdigest() != meta.get("empreinte"):
        raise PaquetInvalide("somme_controle")
    try:
        objets = json.loads(membres["donnees.json"])
        if not isinstance(objets, dict):
            raise ValueError
    except ValueError:
        raise PaquetInvalide("illisible", "donnees.json")
    if meta.get("app") != app:
        raise PaquetInvalide("app")
    if meta.get("utilisateur") != utilisateur:
        raise PaquetInvalide("utilisateur")
    if _version(meta.get("version_schema")) > _version(version_schema_app):
        raise PaquetInvalide("version_future")
    return meta, objets


def valider_bloc_contrat(bloc) -> list:
    """Erreurs du bloc `contrat_donnees` d'un manifeste (liste vide = conforme)."""
    if not isinstance(bloc, dict):
        return ["contrat_donnees absent ou n'est pas un objet"]
    erreurs = []
    v = bloc.get("version_schema")
    if not (isinstance(v, str) and v.isdigit()):
        erreurs.append("version_schema doit être une chaîne numérique")
    for action in ACTIONS:
        a = bloc.get(action)
        if not isinstance(a, dict):
            erreurs.append(f"{action} manquant")
            continue
        if a.get("methode") != "POST":
            erreurs.append(f"{action}.methode doit être POST")
        chemin = a.get("chemin")
        if not (isinstance(chemin, str) and chemin.startswith("/support/")):
            erreurs.append(f"{action}.chemin doit commencer par /support/")
    return erreurs
```

- [ ] **Step 4 : Vérifier le succès**

Run : `python -m pytest shared/test_contrat_donnees.py -q`
Expected : tous PASS (≈ 18 tests).

- [ ] **Step 5 : Commit**

```bash
git add shared/contrat_donnees.py shared/test_contrat_donnees.py
git commit -m "feat(s248): bibliothèque du paquet signé du contrat de données"
```

---

### Task 2 : Harnais de conformité réutilisable

**Files :**
- Create : `shared/conformite_contrat.py`
- Test : `shared/test_conformite_contrat.py`

**Interfaces :**
- Produces :
  - `class Refus(Exception)` — l'adaptateur la lève quand l'app refuse (HTTP 4xx)
  - `verifier_conformite(a, u1="claire", u2="marina") -> None` où l'adaptateur `a` fournit : `peupler(u)`, `exporter(u) -> bytes`, `etat(u) -> tuple[dict, str]` (comptages, empreinte), `reinitialiser(u, empreinte)`, `importer(u, octets)`. Lève `AssertionError` si non conforme.

- [ ] **Step 1 : Écrire le test (adaptateur en mémoire conforme, puis cassé)**

`shared/test_conformite_contrat.py` :

```python
import pytest

from shared import contrat_donnees as C
from shared.conformite_contrat import Refus, verifier_conformite

CLE = b"k"


class AppMemoire:
    """App de référence : un dict {utilisateur: [objets]}. `fuite=True` simule une app dont
    l'export/reset ignore le cloisonnement."""

    def __init__(self, fuite=False):
        self.d = {}
        self.fuite = fuite

    def _objets(self, u):
        if self.fuite:
            return {"notes": [n for liste in self.d.values() for n in liste]}
        return {"notes": list(self.d.get(u, []))}

    def peupler(self, u):
        self.d[u] = [{"id": f"{u}-1", "t": "a"}, {"id": f"{u}-2", "t": "b"}]

    def exporter(self, u):
        return C.construire_paquet("memoire", u, "1", self._objets(u), CLE)

    def etat(self, u):
        o = self._objets(u)
        return C.comptages(o), C.empreinte(o)

    def reinitialiser(self, u, empreinte):
        if self.etat(u)[1] != empreinte:
            raise Refus("empreinte")
        if self.fuite:
            self.d.clear()
        else:
            self.d[u] = []

    def importer(self, u, octets):
        try:
            _, o = C.lire_paquet(octets, CLE, "memoire", u, "1")
        except C.PaquetInvalide as e:
            raise Refus(e.raison)
        self.d[u] = o["notes"]


def test_app_conforme_passe():
    verifier_conformite(AppMemoire())


def test_app_qui_fuit_echoue():
    with pytest.raises(AssertionError):
        verifier_conformite(AppMemoire(fuite=True))
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `python -m pytest shared/test_conformite_contrat.py -q`
Expected : erreur d'import (`conformite_contrat`).

- [ ] **Step 3 : Implémenter**

`shared/conformite_contrat.py` :

```python
"""Harnais de conformité du contrat de données (S248) — réutilisable par toute app candidate.

L'app fournit un ADAPTATEUR (souvent un client de test HTTP) :
    peupler(u)                -> crée des données pour l'utilisateur u
    exporter(u)               -> octets du paquet
    etat(u)                   -> (comptages: dict, empreinte: str) de l'état courant de u
    reinitialiser(u, empreinte) -> remet u à zéro ; lève Refus si l'empreinte ≠ état courant
    importer(u, octets)       -> réinjecte ; lève Refus si le paquet est refusé
`Refus` = l'app a répondu par un refus (HTTP 4xx). Toute violation lève AssertionError.
"""


class Refus(Exception):
    """L'app refuse l'opération (à lever par l'adaptateur sur un refus applicatif)."""


def _doit_refuser(f, message):
    try:
        f()
    except Refus:
        return
    raise AssertionError(message)


def _altere(octets: bytes) -> bytes:
    milieu = len(octets) // 2
    return octets[:milieu] + bytes([octets[milieu] ^ 0xFF]) + octets[milieu + 1:]


def verifier_conformite(a, u1: str = "claire", u2: str = "marina") -> None:
    a.peupler(u1)
    a.peupler(u2)
    avant_u1, avant_u2 = a.etat(u1), a.etat(u2)
    assert sum(avant_u1[0].values()) > 0, "peupler() doit créer des données"
    assert avant_u1 != avant_u2, "les deux utilisateurs doivent avoir des données distinctes"

    paquet = a.exporter(u1)

    # Garde-fous : refus d'un reset sans empreinte exacte, d'un paquet falsifié ou étranger.
    _doit_refuser(lambda: a.reinitialiser(u1, "empreinte-fausse"),
                  "reinitialiser doit refuser une empreinte qui ne correspond pas")
    assert a.etat(u1) == avant_u1, "un reset refusé ne doit rien modifier"
    _doit_refuser(lambda: a.importer(u1, _altere(paquet)),
                  "importer doit refuser un paquet falsifié")
    _doit_refuser(lambda: a.importer(u2, paquet),
                  "importer doit refuser le paquet d'un autre utilisateur")
    assert a.etat(u2) == avant_u2, "un import refusé ne doit rien modifier"

    # Séquence nominale + isolation.
    a.reinitialiser(u1, avant_u1[1])
    assert sum(a.etat(u1)[0].values()) == 0, "après reset, l'espace de u1 doit être vide"
    assert a.etat(u2) == avant_u2, "le reset de u1 ne doit PAS toucher u2"
    a.importer(u1, paquet)
    assert a.etat(u1) == avant_u1, "export→reset→import doit redonner un état identique"
    assert a.etat(u2) == avant_u2, "l'import de u1 ne doit PAS toucher u2"
```

Note : dans le cas « app qui fuit », `peupler` écrase les listes et `etat(u1)` regroupe tout ; l'assertion `avant_u1 != avant_u2` échoue déjà → AssertionError attendu (c'est une violation du cloisonnement détectée tôt).

- [ ] **Step 4 : Vérifier le succès**

Run : `python -m pytest shared/test_conformite_contrat.py -q`
Expected : 2 PASS.

- [ ] **Step 5 : Commit**

```bash
git add shared/conformite_contrat.py shared/test_conformite_contrat.py
git commit -m "feat(s248): harnais de conformité réutilisable du contrat de données"
```

---

### Task 3 : Studio — `support.py` (logique pure) + synchro de la bibliothèque

**Files :**
- Modify : `outils/sync_socle.sh`
- Create (copie) : `briques/studio/contrat_donnees.py`
- Modify : `briques/studio/studio.py` (ajouter `identite_effective`)
- Modify : `briques/studio/main.py:72-83` (alias)
- Create : `briques/studio/support.py`
- Test : `briques/studio/test_support.py`

**Interfaces :**
- Consumes : `contrat_donnees` (Task 1).
- Produces (module `support`) :
  - `APP = "studio"`, `VERSION_SCHEMA = "1"`, `MIGRATIONS: dict[int, callable]`
  - `class Refus(Exception)` (`.raison` ∈ {`empreinte`, `conflit`, `objet_etranger`, `incoherent`, `format`, `migration`, `verification`})
  - `exporter(utilisateur, racine=None) -> dict` (clés toujours présentes : `series`, `profils`, `journaux`, `comptes`, `ponts`)
  - `reinitialiser(utilisateur, empreinte_attendue, racine=None) -> dict` (comptages supprimés)
  - `importer(utilisateur, objets, racine=None) -> dict` (comptages écrits)
  - `migrer(objets, version_paquet) -> dict`
  - `verifier(octets, cle, utilisateur) -> dict` (`{"ok", "comptages", "empreinte", "version_schema"}`)
  - `_appartient(objet, utilisateur, serie: bool) -> bool` (point unique du cloisonnement, ciblé par la mutation en Task 4)

- [ ] **Step 1 : Synchro de la bibliothèque**

Dans `outils/sync_socle.sh`, après la ligne `CSS_BRIQUES=(...)`, ajouter :

```bash
# Consommateurs de la bibliothèque du contrat de données (S248) — stdlib pure.
CONTRAT_BRIQUES=(studio)
```

et, avant le `echo "Assets front synchronisés…"` final :

```bash
for b in "${CONTRAT_BRIQUES[@]}"; do
  cp "shared/contrat_donnees.py" "briques/$b/contrat_donnees.py"
  echo "→ briques/$b/contrat_donnees.py"; n=$((n+1))
done
```

Run : `bash outils/sync_socle.sh && ls briques/studio/contrat_donnees.py`
Expected : le fichier existe.

- [ ] **Step 2 : Déplacer `identite_effective` dans `studio.py`**

Dans `briques/studio/studio.py`, ajouter après `_save_compte` (avant « Hiérarchie ») :

```python
def identite_effective(objet: dict) -> str:
    """Normalise `cree_par` à la LECTURE (jamais réécrit dans le fichier, S187) : une valeur
    legacy — mode ouvert historique (`"public"`) ou ancienne `STUDIO_KEY` brute d'avant S187 —
    est traitée comme `"perso"`, le bucket mono-user par défaut du dialecte par personne.
    N'affecte PAS le dialecte BYO : la clé d'un client reste sa propre identité."""
    valeur = objet.get("cree_par")
    studio_key = os.environ.get("STUDIO_KEY", "").strip()
    if studio_key and (valeur in (None, "public") or valeur == studio_key):
        return "perso"
    return valeur if valeur is not None else "public"
```

Dans `briques/studio/main.py`, remplacer le corps de `_identite_effective` (lignes 72-83) par :

```python
def _identite_effective(serie: dict) -> str:
    """Voir `studio.identite_effective` (même règle, S187) — conservé comme alias."""
    return S.identite_effective(serie)
```

Run : `cd briques/studio && python -m pytest test_isolation_personne.py test_auth.py -q`
Expected : PASS (comportement inchangé).

- [ ] **Step 3 : Écrire les tests de `support.py`**

`briques/studio/test_support.py` :

```python
import json
import os

import pytest

import contrat_donnees as C
import stockage_pont
import studio as S
import support as SUP


@pytest.fixture
def racine(tmp_path, monkeypatch):
    """Studio entier redirigé vers un dossier jetable (séries, profils, comptes, ponts)."""
    r = str(tmp_path)
    for sous in ("profils", "comptes", "pont"):
        os.makedirs(os.path.join(r, sous))
    monkeypatch.setattr(S, "ATELIERS_DIR", r)
    monkeypatch.setattr(S, "PROFILS_DIR", os.path.join(r, "profils"))
    monkeypatch.setattr(S, "COMPTES_DIR", os.path.join(r, "comptes"))
    monkeypatch.setattr(stockage_pont, "ATELIERS_DIR", r)
    monkeypatch.setattr(stockage_pont, "PONT_DIR", os.path.join(r, "pont"))
    monkeypatch.delenv("STUDIO_KEY", raising=False)
    return r


def peupler(u):
    sid, pid = f"serie-{u}", f"profil-{u}"
    S._save({"id": sid, "titre": f"Série de {u}", "cree_par": u, "episodes": []})
    S._save_profil({"id": pid, "nom": f"Enfant de {u}", "cible": "6-8", "cree_par": u})
    S._ajouter_evenement(pid, {"type": "ecoute", "serie_id": sid})
    S._save_compte(u, {"nom_famille": f"Famille {u}"})
    stockage_pont.fixer_monde(sid, f"monde-{u}")


def test_exporter_ne_contient_que_l_utilisateur(racine):
    peupler("claire")
    peupler("marina")
    o = SUP.exporter("claire")
    assert [s["id"] for s in o["series"]] == ["serie-claire"]
    assert [p["id"] for p in o["profils"]] == ["profil-claire"]
    assert [j["profil_id"] for j in o["journaux"]] == ["profil-claire"]
    assert o["comptes"] == [{"nom_famille": "Famille claire"}]
    assert [p["serie_id"] for p in o["ponts"]] == ["serie-claire"]
    assert "marina" not in json.dumps(o)


def test_exporter_cles_toujours_presentes_meme_vide(racine):
    assert SUP.exporter("personne") == {
        "series": [], "profils": [], "journaux": [], "comptes": [], "ponts": []}


def test_export_deterministe(racine):
    peupler("claire")
    assert C.empreinte(SUP.exporter("claire")) == C.empreinte(SUP.exporter("claire"))


def test_reinitialiser_refuse_si_empreinte_differente(racine):
    peupler("claire")
    with pytest.raises(SUP.Refus) as e:
        SUP.reinitialiser("claire", "empreinte-fausse")
    assert e.value.raison == "empreinte"
    assert os.path.exists(S._path("serie-claire"))


def test_reinitialiser_efface_claire_et_pas_marina(racine):
    peupler("claire")
    peupler("marina")
    emp = C.empreinte(SUP.exporter("claire"))
    supprimes = SUP.reinitialiser("claire", emp)
    assert supprimes["series"] == 1
    assert sum(C.comptages(SUP.exporter("claire")).values()) == 0
    assert sum(C.comptages(SUP.exporter("marina")).values()) == 5


def test_reinitialiser_detecte_une_modification_apres_export(racine):
    peupler("claire")
    emp = C.empreinte(SUP.exporter("claire"))
    S._ajouter_evenement("profil-claire", {"type": "ecoute", "serie_id": "serie-claire"})
    with pytest.raises(SUP.Refus):
        SUP.reinitialiser("claire", emp)


def test_aller_retour_identique(racine):
    peupler("claire")
    avant = SUP.exporter("claire")
    SUP.reinitialiser("claire", C.empreinte(avant))
    SUP.importer("claire", avant)
    assert SUP.exporter("claire") == avant
    assert S._load("serie-claire")["titre"] == "Série de claire"   # relisible par le Studio
    assert S._load_compte("claire") == {"nom_famille": "Famille claire"}


def test_importer_refuse_objet_d_un_autre_utilisateur(racine):
    peupler("marina")
    o = SUP.exporter("marina")
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "objet_etranger"
    assert SUP.exporter("claire")["series"] == []


def test_importer_refuse_conflit_avec_un_objet_d_un_autre(racine):
    peupler("marina")
    o = {"series": [{"id": "serie-marina", "titre": "vol", "cree_par": "claire"}],
         "profils": [], "journaux": [], "comptes": [], "ponts": []}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "conflit"
    assert S._load("serie-marina")["titre"] == "Série de marina"


def test_importer_ne_garde_rien_si_refus(racine):
    peupler("marina")
    o = {"series": [{"id": "ok-1", "titre": "A", "cree_par": "claire"},
                    {"id": "serie-marina", "titre": "vol", "cree_par": "claire"}],
         "profils": [], "journaux": [], "comptes": [], "ponts": []}
    with pytest.raises(SUP.Refus):
        SUP.importer("claire", o)
    assert not os.path.exists(S._path("ok-1"))   # rien d'écrit avant la validation complète


@pytest.mark.parametrize("mauvais_id", ["../evil", "a/b", "", "x" * 65, "a b"])
def test_importer_refuse_les_identifiants_dangereux(racine, mauvais_id):
    o = {"series": [{"id": mauvais_id, "cree_par": "claire"}],
         "profils": [], "journaux": [], "comptes": [], "ponts": []}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "format"


def test_importer_refuse_journal_orphelin(racine):
    o = {"series": [], "profils": [], "comptes": [], "ponts": [],
         "journaux": [{"profil_id": "inconnu", "evenements": []}]}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "incoherent"


def test_importer_refuse_cle_inconnue(racine):
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", {"series": [], "autre": []})
    assert e.value.raison == "format"


def test_migrer_version_courante_inchangee():
    o = {"series": []}
    assert SUP.migrer(o, "1") is o


def test_migrer_sans_crochet_refuse(monkeypatch):
    monkeypatch.setattr(SUP, "VERSION_SCHEMA", "2")
    with pytest.raises(SUP.Refus) as e:
        SUP.migrer({"series": []}, "1")
    assert e.value.raison == "migration"


def test_migrer_applique_les_crochets(monkeypatch):
    monkeypatch.setattr(SUP, "VERSION_SCHEMA", "3")
    monkeypatch.setattr(SUP, "MIGRATIONS", {
        1: lambda o: {**o, "v2": True}, 2: lambda o: {**o, "v3": True}})
    assert SUP.migrer({"series": []}, "1") == {"series": [], "v2": True, "v3": True}


def test_verifier_valide_et_ne_touche_pas_le_vrai_volume(racine):
    peupler("claire")
    objets = SUP.exporter("claire")
    paquet = C.construire_paquet("studio", "claire", "1", objets, b"k")
    SUP.reinitialiser("claire", C.empreinte(objets))        # espace réel vide
    rapport = SUP.verifier(paquet, b"k", "claire")
    assert rapport["ok"] and rapport["comptages"]["series"] == 1
    assert rapport["empreinte"] == C.empreinte(objets)
    assert SUP.exporter("claire")["series"] == []           # la vérification n'a rien écrit


def test_verifier_refuse_paquet_falsifie(racine):
    peupler("claire")
    paquet = C.construire_paquet("studio", "claire", "1", SUP.exporter("claire"), b"k")
    with pytest.raises(C.PaquetInvalide):
        SUP.verifier(paquet, b"autre-cle", "claire")
```

- [ ] **Step 4 : Vérifier l'échec**

Run : `cd briques/studio && python -m pytest test_support.py -q`
Expected : erreur d'import (`No module named 'support'`).

- [ ] **Step 5 : Implémenter `support.py`**

`briques/studio/support.py` :

```python
"""Contrat de données utilisateur du Studio (S248) — export / reset / import / vérification.

LOGIQUE PURE sur les fichiers JSON du Studio, sans FastAPI. Toutes les fonctions prennent une
`racine` (défaut : le volume réel `S.ATELIERS_DIR`) : la VÉRIFICATION rejoue l'import dans un
dossier jetable puis ré-exporte, et compare l'empreinte — preuve que le paquet est restaurable.

Disposition sous la racine (identique au volume réel) :
  {id}.json                séries           profils/{id}.json            profils lecteurs
  profils/{id}-journal.json journaux        comptes/{sha256(u)[:16]}.json compte (nom de famille)
  pont/{serie_id}.json     lien personnages ↔ world-engine

Limite documentée : les médias (images, audio) des séries vivent dans d'autres briques ; le
paquet n'en contient que les références.
"""
import hashlib
import json
import os
import re
import tempfile
from typing import Optional

import contrat_donnees as C
import studio as S

APP = "studio"
VERSION_SCHEMA = "1"
# {version_source: fonction(objets) -> objets en version_source + 1}
MIGRATIONS: dict = {}

CLES = ("series", "profils", "journaux", "comptes", "ponts")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Refus(Exception):
    def __init__(self, raison: str, detail: str = ""):
        super().__init__(f"{raison} : {detail}" if detail else raison)
        self.raison = raison


def _chemins(racine: str) -> dict:
    return {"series": racine, "profils": os.path.join(racine, "profils"),
            "comptes": os.path.join(racine, "comptes"), "ponts": os.path.join(racine, "pont")}


def _compte_chemin(racine: str, utilisateur: str) -> str:
    h = hashlib.sha256(utilisateur.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_chemins(racine)["comptes"], f"{h}.json")


def _appartient(objet: dict, utilisateur: str, serie: bool) -> bool:
    """POINT UNIQUE du cloisonnement : à qui appartient cet objet ? (séries : identité
    normalisée comme le Studio ; profils : égalité stricte comme `_profil_de`.)"""
    if serie:
        return S.identite_effective(objet) == utilisateur
    return objet.get("cree_par") == utilisateur


def _json_dossier(dossier: str, exclure_suffixe: Optional[str] = None) -> list:
    out = []
    if not os.path.isdir(dossier):
        return out
    for fn in sorted(os.listdir(dossier)):
        chemin = os.path.join(dossier, fn)
        if not fn.endswith(".json") or not os.path.isfile(chemin):
            continue
        if exclure_suffixe and fn.endswith(exclure_suffixe):
            continue
        try:
            with open(chemin, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _lire(chemin: str):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def exporter(utilisateur: str, racine: Optional[str] = None) -> dict:
    racine = racine or S.ATELIERS_DIR
    d = _chemins(racine)
    series = [s for s in _json_dossier(d["series"]) if _appartient(s, utilisateur, True)]
    profils = [p for p in _json_dossier(d["profils"], "-journal.json")
               if _appartient(p, utilisateur, False)]
    journaux = []
    for p in profils:
        j = _lire(os.path.join(d["profils"], f"{p['id']}-journal.json"))
        if isinstance(j, dict):
            journaux.append(j)
    compte = _lire(_compte_chemin(racine, utilisateur))
    ponts = []
    for s in series:
        pt = _lire(os.path.join(d["ponts"], f"{s['id']}.json"))
        if isinstance(pt, dict):
            ponts.append(pt)
    return {
        "series": sorted(series, key=lambda x: str(x.get("id"))),
        "profils": sorted(profils, key=lambda x: str(x.get("id"))),
        "journaux": sorted(journaux, key=lambda x: str(x.get("profil_id"))),
        "comptes": [compte] if isinstance(compte, dict) else [],
        "ponts": sorted(ponts, key=lambda x: str(x.get("serie_id"))),
    }


def _supprimer(chemin: str) -> None:
    try:
        os.remove(chemin)
    except FileNotFoundError:
        pass


def reinitialiser(utilisateur: str, empreinte_attendue: str,
                  racine: Optional[str] = None) -> dict:
    """Remet l'espace de `utilisateur` à zéro. Refuse sans l'empreinte EXACTE des données
    courantes : le paquet exporté couvre donc bien l'état qu'on s'apprête à effacer."""
    racine = racine or S.ATELIERS_DIR
    d = _chemins(racine)
    objets = exporter(utilisateur, racine)
    if C.empreinte(objets) != empreinte_attendue:
        raise Refus("empreinte", "les données ont changé depuis l'export (ou paquet d'un autre état)")
    for s in objets["series"]:
        _supprimer(os.path.join(d["series"], f"{s['id']}.json"))
    for p in objets["profils"]:
        _supprimer(os.path.join(d["profils"], f"{p['id']}.json"))
        _supprimer(os.path.join(d["profils"], f"{p['id']}-journal.json"))
    for pt in objets["ponts"]:
        _supprimer(os.path.join(d["ponts"], f"{pt['serie_id']}.json"))
    if objets["comptes"]:
        _supprimer(_compte_chemin(racine, utilisateur))
    return C.comptages(objets)


def migrer(objets: dict, version_paquet) -> dict:
    v, cible = int(version_paquet), int(VERSION_SCHEMA)
    while v < cible:
        f = MIGRATIONS.get(v)
        if f is None:
            raise Refus("migration", f"aucune migration depuis la version {v}")
        objets = f(objets)
        v += 1
    return objets


def _valider(utilisateur: str, objets: dict, racine: str) -> None:
    """Toutes les vérifications AVANT la moindre écriture."""
    d = _chemins(racine)
    if not isinstance(objets, dict) or set(objets) - set(CLES):
        raise Refus("format", "clés inattendues")
    for cle in CLES:
        if not isinstance(objets.get(cle, []), list):
            raise Refus("format", f"{cle} doit être une liste")
    ids_series, ids_profils = set(), set()
    for s in objets.get("series", []):
        if not isinstance(s, dict) or not _ID.match(str(s.get("id", ""))):
            raise Refus("format", "identifiant de série invalide")
        ids_series.add(s["id"])
        if not _appartient(s, utilisateur, True):
            raise Refus("objet_etranger", "série")
        existant = _lire(os.path.join(d["series"], f"{s['id']}.json"))
        if isinstance(existant, dict) and not _appartient(existant, utilisateur, True):
            raise Refus("conflit", "série")
    for p in objets.get("profils", []):
        if not isinstance(p, dict) or not _ID.match(str(p.get("id", ""))):
            raise Refus("format", "identifiant de profil invalide")
        ids_profils.add(p["id"])
        if not _appartient(p, utilisateur, False):
            raise Refus("objet_etranger", "profil")
        existant = _lire(os.path.join(d["profils"], f"{p['id']}.json"))
        if isinstance(existant, dict) and not _appartient(existant, utilisateur, False):
            raise Refus("conflit", "profil")
    for j in objets.get("journaux", []):
        if not isinstance(j, dict) or j.get("profil_id") not in ids_profils:
            raise Refus("incoherent", "journal sans profil")
    for pt in objets.get("ponts", []):
        if not isinstance(pt, dict) or pt.get("serie_id") not in ids_series:
            raise Refus("incoherent", "pont sans série")
    if len(objets.get("comptes", [])) > 1 or any(
            not isinstance(c, dict) for c in objets.get("comptes", [])):
        raise Refus("format", "compte")


def _ecrire(chemin: str, data: dict) -> None:
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, chemin)


def importer(utilisateur: str, objets: dict, racine: Optional[str] = None) -> dict:
    racine = racine or S.ATELIERS_DIR
    d = _chemins(racine)
    _valider(utilisateur, objets, racine)
    for s in objets.get("series", []):
        _ecrire(os.path.join(d["series"], f"{s['id']}.json"), s)
    for p in objets.get("profils", []):
        _ecrire(os.path.join(d["profils"], f"{p['id']}.json"), p)
    for j in objets.get("journaux", []):
        _ecrire(os.path.join(d["profils"], f"{j['profil_id']}-journal.json"), j)
    for pt in objets.get("ponts", []):
        _ecrire(os.path.join(d["ponts"], f"{pt['serie_id']}.json"), pt)
    for c in objets.get("comptes", []):
        _ecrire(_compte_chemin(racine, utilisateur), c)
    return C.comptages({k: objets.get(k, []) for k in CLES})


def verifier(octets: bytes, cle: bytes, utilisateur: str) -> dict:
    """Prouve qu'un paquet est restaurable : lecture signée, import dans un dossier JETABLE,
    ré-export, comparaison de l'empreinte. N'écrit jamais dans le volume réel."""
    meta, objets = C.lire_paquet(octets, cle, APP, utilisateur, VERSION_SCHEMA)
    objets = migrer(objets, meta["version_schema"])
    with tempfile.TemporaryDirectory() as tmp:
        importer(utilisateur, objets, racine=tmp)
        relu = exporter(utilisateur, racine=tmp)
    if C.empreinte(relu) != C.empreinte(objets):
        raise Refus("verification", "le ré-export ne redonne pas les mêmes données")
    return {"ok": True, "comptages": C.comptages(relu), "empreinte": C.empreinte(relu),
            "version_schema": meta["version_schema"]}
```

- [ ] **Step 6 : Vérifier le succès**

Run : `cd briques/studio && python -m pytest test_support.py -q`
Expected : tous PASS.

Si `test_verifier_valide_…` échoue sur l'empreinte : un paquet de version inférieure migré change `objets` ; la comparaison se fait volontairement sur `objets` migrés (déjà le cas).

- [ ] **Step 7 : Non-régression Studio**

Run : `cd briques/studio && python -m pytest -q -x`
Expected : PASS (aucune régression ; `identite_effective` est un déplacement pur).

- [ ] **Step 8 : Commit**

```bash
git add outils/sync_socle.sh briques/studio/contrat_donnees.py briques/studio/studio.py \
        briques/studio/main.py briques/studio/support.py briques/studio/test_support.py
git commit -m "feat(s248): export/reset/import/vérification des données utilisateur du Studio"
```

---

### Task 4 : Studio — routes `/support/*`, conformité, mutation, manifeste

**Files :**
- Modify : `briques/studio/main.py` (imports + routes)
- Modify : `briques/studio/manifest.json`
- Test : `briques/studio/test_support_routes.py`

**Interfaces :**
- Consumes : `support` (Task 3), `contrat_donnees` (Task 1), `conformite_contrat` (Task 2).
- Produces (HTTP, tous `POST`, header `X-Support-Key`) :
  - `/support/exporter` body `{"utilisateur"}` → octets `application/gzip` + en-têtes `X-Empreinte`, `X-Comptages` (JSON)
  - `/support/verifier?utilisateur=` body = octets du paquet → `{"ok", "comptages", "empreinte", "version_schema"}`
  - `/support/reinitialiser` body `{"utilisateur", "empreinte"}` → `{"ok": true, "supprimes": {...}}` ; 409 si empreinte/conflit
  - `/support/importer?utilisateur=` body = octets → `{"ok": true, "comptages": {...}}`
  - Codes : 503 clé non configurée ; 401 clé fausse ; 409 `empreinte`/`conflit` ; 422 autres refus (`detail` = raison seule, sans donnée).

- [ ] **Step 1 : Écrire les tests**

`briques/studio/test_support_routes.py` :

```python
import json
import os

import pytest
from fastapi.testclient import TestClient

import contrat_donnees as C
import main
import stockage_pont
import studio as S
import support as SUP

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared.conformite_contrat import Refus, verifier_conformite  # noqa: E402

CLE = "cle-support-test"
client = TestClient(main.app)
H = {"X-Support-Key": CLE}


@pytest.fixture(autouse=True)
def volume_jetable(tmp_path, monkeypatch):
    r = str(tmp_path)
    for sous in ("profils", "comptes", "pont"):
        os.makedirs(os.path.join(r, sous))
    monkeypatch.setattr(S, "ATELIERS_DIR", r)
    monkeypatch.setattr(S, "PROFILS_DIR", os.path.join(r, "profils"))
    monkeypatch.setattr(S, "COMPTES_DIR", os.path.join(r, "comptes"))
    monkeypatch.setattr(stockage_pont, "ATELIERS_DIR", r)
    monkeypatch.setattr(stockage_pont, "PONT_DIR", os.path.join(r, "pont"))
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", CLE)
    monkeypatch.delenv("STUDIO_KEY", raising=False)


def peupler(u):
    sid, pid = f"serie-{u}", f"profil-{u}"
    S._save({"id": sid, "titre": f"Série de {u}", "cree_par": u, "episodes": []})
    S._save_profil({"id": pid, "nom": f"Enfant de {u}", "cible": "6-8", "cree_par": u})
    S._ajouter_evenement(pid, {"type": "ecoute", "serie_id": sid})
    S._save_compte(u, {"nom_famille": f"Famille {u}"})
    stockage_pont.fixer_monde(sid, f"monde-{u}")


# ── Authentification dédiée ─────────────────────────────────────
def test_support_desactive_sans_cle_configuree(monkeypatch):
    monkeypatch.delenv("STUDIO_SUPPORT_KEY")
    r = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 503


def test_cle_fausse_ou_absente_401():
    assert client.post("/support/exporter", json={"utilisateur": "c"}).status_code == 401
    assert client.post("/support/exporter", json={"utilisateur": "c"},
                       headers={"X-Support-Key": "fausse"}).status_code == 401


def test_la_cle_studio_et_les_api_keys_n_ouvrent_pas_le_support(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    monkeypatch.setattr(main, "API_KEYS", {"cle-byo"})
    for k in ("cle-coeur", "cle-byo"):
        r = client.post("/support/exporter", json={"utilisateur": "claire"},
                        headers={"X-API-Key": k, "X-Support-Key": k})
        assert r.status_code == 401


def test_utilisateur_vide_422():
    assert client.post("/support/exporter", json={"utilisateur": "  "}, headers=H).status_code == 422


# ── Routes ──────────────────────────────────────────────────────
def test_exporter_expose_les_metadonnees_en_entetes():
    peupler("claire")
    r = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 200
    assert json.loads(r.headers["x-comptages"])["series"] == 1
    meta, objets = C.lire_paquet(r.content, CLE.encode(), "studio", "claire", "1")
    assert r.headers["x-empreinte"] == meta["empreinte"] == C.empreinte(objets)


def test_verifier_route():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    r = client.post("/support/verifier", params={"utilisateur": "claire"}, content=paquet, headers=H)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_verifier_paquet_falsifie_422_sans_donnee_perso():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    mauvais = paquet[:20] + bytes([paquet[20] ^ 0xFF]) + paquet[21:]
    r = client.post("/support/verifier", params={"utilisateur": "claire"}, content=mauvais, headers=H)
    assert r.status_code == 422
    assert "claire" not in r.text.replace('"detail"', "") or r.json()["detail"] in {
        "illisible", "signature", "somme_controle"}


def test_reinitialiser_mauvaise_empreinte_409_et_rien_efface():
    peupler("claire")
    r = client.post("/support/reinitialiser",
                    json={"utilisateur": "claire", "empreinte": "faux"}, headers=H)
    assert r.status_code == 409
    assert os.path.exists(S._path("serie-claire"))


def test_importer_paquet_d_un_autre_utilisateur_422():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    r = client.post("/support/importer", params={"utilisateur": "marina"}, content=paquet, headers=H)
    assert r.status_code == 422 and r.json()["detail"] == "utilisateur"


def test_importer_conflit_409():
    peupler("marina")
    objets = {"series": [{"id": "serie-marina", "cree_par": "claire"}], "profils": [],
              "journaux": [], "comptes": [], "ponts": []}
    paquet = C.construire_paquet("studio", "claire", "1", objets, CLE.encode())
    r = client.post("/support/importer", params={"utilisateur": "claire"}, content=paquet, headers=H)
    assert r.status_code == 409


# ── Conformité (harnais réutilisable) + mutation de l'isolation ─
class AdaptateurStudio:
    def peupler(self, u):
        peupler(u)

    def exporter(self, u):
        r = client.post("/support/exporter", json={"utilisateur": u}, headers=H)
        assert r.status_code == 200
        return r.content

    def etat(self, u):
        r = client.post("/support/exporter", json={"utilisateur": u}, headers=H)
        return json.loads(r.headers["x-comptages"]), r.headers["x-empreinte"]

    def reinitialiser(self, u, empreinte):
        r = client.post("/support/reinitialiser",
                        json={"utilisateur": u, "empreinte": empreinte}, headers=H)
        if r.status_code >= 400:
            raise Refus(r.json()["detail"])

    def importer(self, u, octets):
        r = client.post("/support/importer", params={"utilisateur": u}, content=octets, headers=H)
        if r.status_code >= 400:
            raise Refus(r.json()["detail"])


def test_studio_est_conforme_au_contrat():
    verifier_conformite(AdaptateurStudio())


def test_mutation_filtre_utilisateur_neutralise_est_detecte(monkeypatch):
    """Si le filtre d'appartenance est neutralisé, le harnais DOIT échouer (sinon le test
    d'isolation ne protège rien)."""
    monkeypatch.setattr(SUP, "_appartient", lambda objet, utilisateur, serie: True)
    with pytest.raises(AssertionError):
        verifier_conformite(AdaptateurStudio())


def test_copie_de_la_bibliotheque_a_jour():
    source = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "contrat_donnees.py")
    if not os.path.exists(source):
        pytest.skip("hors monorepo (image Docker)")
    with open(source, "rb") as a, open(C.__file__, "rb") as b:
        assert a.read() == b.read(), "relancer outils/sync_socle.sh"
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `cd briques/studio && python -m pytest test_support_routes.py -q`
Expected : échecs 404 sur `/support/*` (routes absentes).

- [ ] **Step 3 : Implémenter les routes**

Dans `briques/studio/main.py` :

(a) imports en tête (à côté des existants) :

```python
import hmac
from fastapi import Request, Response
import contrat_donnees as C
import support as SUP
```

(b) à la fin du fichier (après la dernière route) :

```python
# ── Contrat de données utilisateur (S248) — routes INTERNES ──────
# Clé DÉDIÉE (STUDIO_SUPPORT_KEY, lue fraîche) : ni STUDIO_KEY ni API_KEYS n'ouvrent ces
# routes. Absente = fonction désactivée (503), jamais de repli ouvert. Le paquet est signé avec
# cette même clé. L'identité visée est EXPLICITE (`utilisateur`) ; le cloisonnement est assuré
# par support.py (filtre unique), pas par X-User-Id.
def cle_support(x_support_key: Optional[str] = Header(None)) -> bytes:
    attendue = os.environ.get("STUDIO_SUPPORT_KEY", "").strip()
    if not attendue:
        raise HTTPException(503, "Support désactivé (STUDIO_SUPPORT_KEY non définie).")
    if not x_support_key or not hmac.compare_digest(x_support_key, attendue):
        raise HTTPException(401, "Clé de support invalide (header X-Support-Key).")
    return attendue.encode("utf-8")


def _cible(utilisateur: str) -> str:
    u = (utilisateur or "").strip()
    if not u:
        raise HTTPException(422, "utilisateur manquant")
    return u


def _refus_http(e: Exception) -> HTTPException:
    """Le `detail` ne porte QUE la raison (jamais de donnée de l'utilisateur)."""
    raison = getattr(e, "raison", "refus")
    return HTTPException(409 if raison in ("empreinte", "conflit") else 422, raison)


class CibleSupport(BaseModel):
    utilisateur: str


class ReinitSupport(BaseModel):
    utilisateur: str
    empreinte: str


@app.post("/support/exporter", tags=["support"])
def support_exporter(body: CibleSupport, cle: bytes = Depends(cle_support)):
    u = _cible(body.utilisateur)
    objets = SUP.exporter(u)
    paquet = C.construire_paquet(SUP.APP, u, SUP.VERSION_SCHEMA, objets, cle)
    return Response(content=paquet, media_type="application/gzip", headers={
        "X-Empreinte": C.empreinte(objets), "X-Comptages": json.dumps(C.comptages(objets))})


@app.post("/support/verifier", tags=["support"])
async def support_verifier(request: Request, utilisateur: str,
                           cle: bytes = Depends(cle_support)):
    u = _cible(utilisateur)
    try:
        return SUP.verifier(await request.body(), cle, u)
    except (C.PaquetInvalide, SUP.Refus) as e:
        raise _refus_http(e)


@app.post("/support/reinitialiser", tags=["support"])
def support_reinitialiser(body: ReinitSupport, _cle: bytes = Depends(cle_support)):
    try:
        return {"ok": True, "supprimes": SUP.reinitialiser(_cible(body.utilisateur), body.empreinte)}
    except SUP.Refus as e:
        raise _refus_http(e)


@app.post("/support/importer", tags=["support"])
async def support_importer(request: Request, utilisateur: str,
                           cle: bytes = Depends(cle_support)):
    u = _cible(utilisateur)
    try:
        meta, objets = C.lire_paquet(await request.body(), cle, SUP.APP, u, SUP.VERSION_SCHEMA)
        objets = SUP.migrer(objets, meta["version_schema"])
        return {"ok": True, "comptages": SUP.importer(u, objets)}
    except (C.PaquetInvalide, SUP.Refus) as e:
        raise _refus_http(e)
```

Note : `main.py` définit-il déjà `Request`/`json` ? `json` oui (ligne 15). Ne dupliquer aucun import existant.

- [ ] **Step 4 : Vérifier le succès**

Run : `cd briques/studio && python -m pytest test_support_routes.py test_support.py -q`
Expected : tous PASS, dont `test_studio_est_conforme_au_contrat` et `test_mutation_filtre_utilisateur_neutralise_est_detecte`.

Si `test_verifier_paquet_falsifie_422_sans_donnee_perso` est fragile (assertion `or`), la simplifier en : `assert r.json()["detail"] in {"illisible", "signature", "somme_controle"}`. Le faire plutôt qu'un contournement.

- [ ] **Step 5 : Déclarer le contrat dans le manifeste**

Dans `briques/studio/manifest.json`, ajouter au niveau racine (à côté de `"taches"`) :

```json
"contrat_donnees": {
  "version_schema": "1",
  "exporter":      {"methode": "POST", "chemin": "/support/exporter"},
  "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
  "importer":      {"methode": "POST", "chemin": "/support/importer"}
},
```

Ajouter un test dans `test_support_routes.py` :

```python
def test_manifeste_declare_un_contrat_valide():
    chemin = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(chemin, encoding="utf-8") as f:
        bloc = json.load(f).get("contrat_donnees")
    assert C.valider_bloc_contrat(bloc) == []
    assert bloc["version_schema"] == SUP.VERSION_SCHEMA
```

Run : `cd briques/studio && python -m pytest -q` puis `cd ../.. && python -m pytest core/test_catalogue.py -q`
Expected : PASS (le Cœur ignore le bloc inconnu ; si un test de contrat manifeste échoue sur la clé nouvelle, l'autoriser explicitement dans ce test et le noter pour la partie 3).

- [ ] **Step 6 : Commit**

```bash
git add briques/studio/main.py briques/studio/manifest.json briques/studio/test_support_routes.py
git commit -m "feat(s248): routes /support/* du Studio, conformité et mutation de l'isolation"
```

---

### Task 5 : Guide du contrat + clôture de la partie 1+2

**Files :**
- Create : `docs/GUIDE-contrat-donnees.md`
- Modify : `docs/sprints/S248-contrat-app-reset-par-utilisateur.md` (décisions + état)
- Modify : `docs/sprints/EPOPEE-livraison-support-assistant.md` (ligne S248 du tableau)

- [ ] **Step 1 : Écrire le guide**

`docs/GUIDE-contrat-donnees.md` — sections, contenu concret (pas de placeholder) :
1. **À quoi ça sert** (une phrase) et **quand ne PAS l'implémenter** (données non isolées par utilisateur → portée « app entière » de S247 seulement).
2. **Le bloc manifeste** : l'exemple JSON de la Task 4 Step 5, avec `version_schema` = entier en chaîne, à incrémenter à chaque changement de format des données exportées.
3. **Les trois routes** : table (méthode, chemin, corps, réponse, codes 409/422/401/503) copiée de la section Interfaces de la Task 4.
4. **Auth** : clé dédiée `<APP>_SUPPORT_KEY` + header `X-Support-Key`, 503 si absente ; ne jamais réutiliser la clé de service du Cœur.
5. **Recette en 5 étapes** : (1) copier `shared/contrat_donnees.py` via `outils/sync_socle.sh` (ajouter la brique à `CONTRAT_BRIQUES`) ; (2) écrire un module de logique pure `support.py` avec `exporter/reinitialiser/importer/verifier` paramétrés par une racine ; (3) isoler le filtre d'appartenance dans UNE fonction ; (4) exposer les routes ; (5) brancher le harnais `shared/conformite_contrat.py` avec un adaptateur (modèle : `AdaptateurStudio` dans `briques/studio/test_support_routes.py`) et le test de mutation.
6. **Règles non négociables** : export déterministe (tri + JSON canonique) ; reset exige l'empreinte exacte ; import valide tout avant d'écrire ; identifiants validés par regex ; messages d'erreur sans donnée perso ; migrations par crochets `{version_source: fonction}`.
7. **Limites connues** : médias hébergés ailleurs non inclus ; pas de verrou contre une écriture concurrente entre l'export et le reset (l'empreinte la détecte au reset, pas pendant l'import).

- [ ] **Step 2 : Mettre à jour la spec S248**

Dans `docs/sprints/S248-contrat-app-reset-par-utilisateur.md`, remplacer la section « Questions à trancher » par « Décisions (2026-11-27) » :
1. App pilote = **Studio** (isolation par personne prouvée S187, `profil_id` portable, données en JSON fichier).
2. Rétention = **14 jours** puis suppression automatique ; restitution à l'utilisateur seulement par lui-même, après validation Telegram (partie 3).
3. Format = **tar.gz** (`meta.json` signé HMAC + `donnees.json` canonique) ; **chiffrement au repos assuré par `livraison`** (le Studio reste stdlib seule), clé hors dépôt (partie 3).
Ajouter : « Reset : l'app exige l'empreinte exacte des données courantes (paquet = état actuel). Clé dédiée `STUDIO_SUPPORT_KEY`. » et l'état « Parties 1+2 codées — plan `docs/superpowers/plans/2026-11-27-s248-partie1-2-contrat-donnees-studio.md` ; partie 3 à planifier ».

Dans `EPOPEE-livraison-support-assistant.md`, ligne S248 : état → « parties 1+2 codées (contrat + Studio) ; partie 3 (outils, chiffrement, approbations) à faire ».

- [ ] **Step 3 : Vérification finale**

Run :
```bash
cd /Users/garinat_t/Desktop/Workplace
python -m pytest shared/test_contrat_donnees.py shared/test_conformite_contrat.py -q
cd briques/studio && python -m pytest -q
```
Expected : tout PASS. Puis `git status` propre hors fichiers committés ; aucun `__pycache__` ajouté.

- [ ] **Step 4 : Commit**

```bash
git add docs/GUIDE-contrat-donnees.md docs/sprints/S248-contrat-app-reset-par-utilisateur.md \
        docs/sprints/EPOPEE-livraison-support-assistant.md
git commit -m "docs(s248): guide du contrat de données, décisions et état des parties 1+2"
```

---

## Auto-revue (spec ↔ plan)

- **Contrat `exporter/reinitialiser/importer` + `version_schema`** : Tasks 1, 3, 4 (bloc manifeste validé par `valider_bloc_contrat`).
- **Paquet = métadonnées + comptages + somme de contrôle, contenu jamais lu par l'assistant** : Task 1 (meta) ; en-têtes `X-Empreinte`/`X-Comptages` seuls (Task 4). ✔
- **Refus : paquet falsifié / mauvaise version / autre utilisateur** : tests Task 1 + conformité (Task 2) + routes (Task 4). ✔
- **« reinitialiser refuse sans paquet vérifié »** : implémenté côté app par l'empreinte exacte (Task 3) ; la preuve « paquet vérifié » côté assistant/approbation = partie 3.
- **Routes internes, identité vérifiée** : clé dédiée + identité explicite + filtre unique (Task 4). ✔
- **Test d'isolation + mutation** : Task 4 (`test_mutation_…`). ✔
- **Gabarit/guide + test de conformité réutilisable** : Tasks 2 et 5. ✔
- **Reporté partie 3 (explicite)** : chiffrement, SeaweedFS, rétention, journal d'accès, outils assistant, validation Cœur du bloc, LIVE.
- **Cohérence des noms** : `support.exporter/reinitialiser/importer/migrer/verifier`, `Refus.raison`, `C.PaquetInvalide.raison`, `APP`, `VERSION_SCHEMA`, `_appartient(objet, utilisateur, serie)` — identiques dans Tasks 3 et 4.
