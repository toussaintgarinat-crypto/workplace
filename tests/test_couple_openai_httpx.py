"""Filet « couple openai/httpx » (S238b, 2026-10-05).

httpx 0.28 a retiré l'argument `proxies` de `httpx.Client`/`AsyncClient` ; openai < 1.55.3
le passe encore. Une unité d'installation qui combine les deux fait lever à **chaque**
construction d'`OpenAI(...)`/`AsyncOpenAI(...)` :

    TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'

Le défaut a frappé deux fois sans qu'aucun test ne le voie, parce que le client n'était
testé qu'avec des doubles :
  • la Mémoire (embeddings cassés en prod de 2026-07-27 à S238) ;
  • la Forge (`forge/core/requirements.txt` : openai==1.54.0 + httpx==0.28.1 depuis
    S205/S206 — tout son LLM cassé, corrigé en S238b).
Dans les deux cas c'est un bump de httpx, fait ailleurs et pour d'autres raisons, qui a
cassé openai : ce filet regarde donc le COUPLE, sur tout le parc, à chaque exécution.

Règle : une unité d'installation = un `requirements*.txt` et tout ce qu'il inclut par
`-r`. Elle est rouge si la version d'openai que pip y retiendrait est < 1.55.3 alors que
celle d'httpx peut être ≥ 0.28. pip retenant la plus haute version admise, on raisonne sur
la **borne haute** des contraintes : `==X` → X ; `<X`/`<=X`/`~=X` → leur plafond ; rien
ou `>=` seul → dernière version publiée, donc httpx ≥ 0.28. Un httpx absent d'une unité qui
déclare openai compte comme non épinglé : openai le tire et pip prend le plus récent.

Limites assumées :
  • une dépendance qui tirerait openai TRANSITIVEMENT (sans le nommer dans un
    requirements) n'est pas vue — c'est l'inventaire des conteneurs du HP (S238b) qui
    couvre ce cas ;
  • une image qui enchaîne plusieurs `pip install -r` distincts dans son Dockerfile forme
    une unité que ce filet ne reconstitue pas (il ne lit que les `-r`) ;
  • les fichiers de contraintes (`-c`) ne sont pas suivis.

`packaging` est une dépendance de pytest : disponible partout où ce filet tourne.
"""
import re
from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

RACINE = Path(__file__).resolve().parent.parent
DOSSIERS = ("briques", "core", "oria-stack")
EXCLUS = {"node_modules", "__pycache__", "apps_exportees"}

OPENAI_MIN_SUR = Version("1.55.3")   # premier openai qui ne passe plus `proxies`
HTTPX_SANS_PROXIES = Version("0.28")  # premier httpx qui a retiré `proxies`


def _exclu(chemin: Path) -> bool:
    parties = chemin.relative_to(RACINE).parts
    if EXCLUS & set(parties) or any(p.startswith(".venv") for p in parties):
        return True
    # `.claude/worktrees` : copies de travail d'autres branches, pas le parc.
    return any(a == ".claude" and b == "worktrees" for a, b in zip(parties, parties[1:]))


def _fichiers_requirements() -> list[Path]:
    trouves = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if base.is_dir():
            trouves += [c for c in base.rglob("requirements*.txt") if not _exclu(c)]
    return sorted(trouves)


# ── Lecture d'une unité d'installation ──────────────────────────────────

def _lignes_logiques(texte: str):
    """Lignes d'un requirements, continuations `\\` recollées, commentaires retirés."""
    tampon = ""
    for brute in texte.splitlines():
        # Règle de pip : `#` en début de ligne ou précédé d'un blanc (espace OU tabulation)
        # ouvre un commentaire ; une ligne de commentaire terminée par `\` n'est pas recollée.
        sans_commentaire = re.split(r"(?:^|\s+)#", brute, maxsplit=1)[0].rstrip()
        if sans_commentaire.endswith("\\"):
            tampon += sans_commentaire[:-1] + " "
            continue
        ligne = (tampon + sans_commentaire).strip()
        tampon = ""
        if ligne:
            yield ligne


def _contraintes(chemin: Path, vus: frozenset = frozenset()) -> dict[str, list[Requirement]]:
    """{nom canonique: [Requirement, …]} pour le fichier ET ses `-r`, récursivement."""
    chemin = chemin.resolve()
    if chemin in vus:  # inclusion circulaire : déjà comptée
        return {}
    vus = vus | {chemin}
    resultat: dict[str, list[Requirement]] = {}
    for ligne in _lignes_logiques(chemin.read_text(encoding="utf-8")):
        if ligne.startswith(("-r ", "--requirement ", "-r", "--requirement=")):
            cible = ligne.split("=", 1)[1] if ligne.startswith("--requirement=") else \
                ligne.split(None, 1)[1] if " " in ligne else ligne[2:]
            inclus = (chemin.parent / cible.strip()).resolve()
            assert inclus.is_file(), f"{chemin.relative_to(RACINE)} : `-r {cible}` introuvable"
            for nom, reqs in _contraintes(inclus, vus).items():
                resultat.setdefault(nom, []).extend(reqs)
            continue
        if ligne.startswith("-"):  # autres options pip (-c, -e, --index-url…) : hors sujet
            continue
        try:
            req = Requirement(ligne.split(" --", 1)[0])  # retire `--hash=…` éventuels
        except InvalidRequirement:
            # URL directe, chemin local… : sans danger tant qu'ils ne visent ni openai ni
            # httpx — sinon le filet ne saurait pas les juger, il refuse plutôt que de taire.
            assert not re.search(r"openai|httpx", ligne, re.I), (
                f"{chemin.relative_to(RACINE)} : ligne illisible pour le filet : {ligne!r}")
            continue
        # `openai @ https://…` : référence directe, la version n'est pas lisible ici.
        assert not (req.url and canonicalize_name(req.name) in ("openai", "httpx")), (
            f"{chemin.relative_to(RACINE)} : ligne illisible pour le filet : {ligne!r}")
        if req.marker is not None and not req.marker.evaluate():
            continue  # marqueur d'environnement : pip ne l'installerait pas
        resultat.setdefault(canonicalize_name(req.name), []).append(req)
    return resultat


# ── Borne haute de ce que pip retiendrait ───────────────────────────────

def _plafond(reqs: list[Requirement]):
    """(version, inclusive) la plus haute admise par l'ensemble des contraintes, ou None si
    aucune borne haute (pip prendra la dernière version publiée)."""
    plafonds = []
    for req in reqs:
        for spec in req.specifier:
            v = Version(spec.version.replace(".*", ""))
            if spec.operator in ("==", "==="):
                if spec.version.endswith(".*"):  # ==1.54.* → < 1.55
                    rel = list(v.release)
                    rel[-1] += 1
                    plafonds.append((Version(".".join(map(str, rel))), False))
                else:
                    plafonds.append((v, True))
            elif spec.operator == "<=":
                plafonds.append((v, True))
            elif spec.operator == "<":
                plafonds.append((v, False))
            elif spec.operator == "~=":  # ~=1.54.0 → < 1.55 ; ~=1.54 → < 2
                rel = list(v.release[:-1])
                rel[-1] += 1
                plafonds.append((Version(".".join(map(str, rel))), False))
    if not plafonds:
        return None
    # Le plus contraignant ; à version égale, l'exclusif l'emporte.
    return min(plafonds, key=lambda p: (p[0], p[1]))


def _openai_trop_ancien(reqs: list[Requirement]) -> bool:
    """Vrai si la plus haute version admise d'openai est < 1.55.3."""
    p = _plafond(reqs)
    if p is None:
        return False
    v, inclusive = p
    return v < OPENAI_MIN_SUR if inclusive else v <= OPENAI_MIN_SUR


def _httpx_sans_proxies(reqs: list[Requirement]) -> bool:
    """Vrai si httpx peut se résoudre en ≥ 0.28 (absent ou sans plafond = dernière version)."""
    p = _plafond(reqs)
    if p is None:
        return True
    v, inclusive = p
    return v >= HTTPX_SANS_PROXIES if inclusive else v > HTTPX_SANS_PROXIES


def _diagnostic(chemin: Path) -> str | None:
    """Message d'échec si l'unité installée par `chemin` combine le couple cassé, sinon None."""
    c = _contraintes(chemin)
    openai = c.get("openai")
    if not openai or not _openai_trop_ancien(openai):
        return None
    httpx = c.get("httpx", [])
    if not _httpx_sans_proxies(httpx):
        return None
    lib = lambda reqs: ", ".join(str(r) for r in reqs) or "non déclaré (le plus récent)"
    return (f"{chemin.relative_to(RACINE)} : openai ({lib(openai)}) < {OPENAI_MIN_SUR} avec "
            f"httpx ({lib(httpx)}) ≥ {HTTPX_SANS_PROXIES} → AsyncOpenAI(...) lève "
            f"TypeError 'proxies' à la construction. Monter openai à ≥ {OPENAI_MIN_SUR}.")


# ── Le filet ────────────────────────────────────────────────────────────

def test_il_y_a_bien_des_fichiers_a_inspecter():
    """Garde-fou du garde-fou : un parcours vide rendrait ce filet vert et inutile."""
    fichiers = _fichiers_requirements()
    assert len(fichiers) > 40, "la collecte des requirements a dû casser"
    # …et il voit bien les deux unités qui déclarent openai aujourd'hui.
    avec_openai = {str(f.relative_to(RACINE)) for f in fichiers if "openai" in _contraintes(f)}
    assert "briques/forge/forge/core/requirements.txt" in avec_openai
    assert "briques/memoire/memory/backend/requirements.txt" in avec_openai


@pytest.mark.parametrize("chemin", _fichiers_requirements(),
                         ids=lambda p: str(p.relative_to(RACINE)))
def test_pas_de_couple_openai_httpx_casse(chemin):
    message = _diagnostic(chemin)
    assert message is None, message


# ── Le filet mord-il ? (cas synthétiques) ───────────────────────────────

def _ecrire(dossier: Path, nom: str, contenu: str) -> Path:
    chemin = dossier / nom
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


@pytest.fixture
def faux_parc(monkeypatch, tmp_path):
    """Les cas synthétiques vivent sous un faux RACINE pour que les messages restent lisibles."""
    monkeypatch.setitem(globals(), "RACINE", tmp_path)
    return tmp_path


def test_mord_sur_l_ancienne_pin_de_la_forge(faux_parc):
    """Le cas réel d'avant S238b : openai==1.54.0 + httpx==0.28.1 dans le même fichier."""
    f = _ecrire(faux_parc, "requirements.txt",
                "httpx==0.28.1\nopenai==1.54.0                     # client LLM\n")
    message = _diagnostic(f)
    assert message and "requirements.txt" in message
    assert "openai==1.54.0" in message and "httpx==0.28.1" in message


def test_mord_a_travers_un_moins_r(faux_parc):
    """Le cas de `briques/forge/requirements-dev.txt` : le couple réparti entre deux fichiers."""
    (faux_parc / "core").mkdir()
    _ecrire(faux_parc / "core", "requirements.txt", "openai==1.54.0\n")
    _ecrire(faux_parc, "requirements.txt", "httpx==0.28.1\n")
    dev = _ecrire(faux_parc, "requirements-dev.txt", "-r requirements.txt\n-r core/requirements.txt\n")
    assert _diagnostic(dev)
    # pris isolément, chaque fichier est sain…
    assert _diagnostic(faux_parc / "requirements.txt") is None


@pytest.mark.parametrize("contenu", [
    "openai==1.54.0\n",                                 # httpx tiré par openai → le plus récent
    "openai==1.54.0\nhttpx>=0.27\n",                    # borne basse seule
    "openai==1.54.0\nhttpx\n",                          # non épinglé
    "openai<1.55\nhttpx==0.28.1\n",                     # plafond exclusif
    "openai~=1.54.0\nhttpx==0.28.1\n",                  # compatible → < 1.55
    "openai==1.54.*\nhttpx==0.28.1\n",                  # joker
    "openai[datalib]==1.40.0 ; python_version >= '3.8'\nhttpx==0.28.1\n",
    "openai==1.55.2 \\\n    --hash=sha256:abc\nHTTPX==0.28.1\n",
    "openai==1.54.0\t# commentaire après tabulation\nhttpx==0.28.1\n",
    "# commentaire terminé par une barre \\\nopenai==1.54.0\nhttpx==0.28.1\n",
])
def test_mord_sur_les_formes_d_ecriture(faux_parc, contenu):
    assert _diagnostic(_ecrire(faux_parc, "requirements.txt", contenu)), contenu


@pytest.mark.parametrize("contenu", [
    "openai==1.55.3\nhttpx==0.28.1\n",                  # la correction S238b / Mémoire
    "openai==2.33.0\nhttpx==0.28.1\n",                  # la Gateway
    "openai==1.54.0\nhttpx==0.27.0\n",                  # vieux couple cohérent
    "openai==1.54.0\nhttpx<0.28\n",
    "openai>=1.0\nhttpx==0.28.1\n",                     # pas de plafond → dernier openai
    "openai\n",
    "httpx==0.28.1\n",                                  # pas d'openai du tout
    "# openai==1.54.0\nhttpx==0.28.1\n",                # commentaire
    "openai==1.54.0 ; python_version < '3'\nhttpx==0.28.1\n",  # marqueur jamais vrai
])
def test_ne_mord_pas_sur_un_couple_sain(faux_parc, contenu):
    assert _diagnostic(_ecrire(faux_parc, "requirements.txt", contenu)) is None, contenu


@pytest.mark.parametrize("contenu", [
    "openai @ https://exemple.invalid/openai-1.54.0.tar.gz\nhttpx==0.28.1\n",
    "git+https://github.com/openai/openai-python@v1.54.0#egg=openai\n",
])
def test_refuse_une_ligne_openai_illisible(faux_parc, contenu):
    """Une forme que le filet ne sait pas juger ne doit pas passer en silence."""
    with pytest.raises(AssertionError, match="illisible"):
        _diagnostic(_ecrire(faux_parc, "requirements.txt", contenu))
