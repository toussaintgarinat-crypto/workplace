"""Recherche plein texte de la brique ingestion (S241) — SQLite FTS5, sans dépendance.

Deux tables FTS5, tenues à jour DANS LA MÊME TRANSACTION que chaque écriture de
`stockage.py` : `documents_recherche` (mots, tokeniseur unicode61) et `documents_trigrammes`
(trigrammes, filet des fautes de frappe). Le texte y est déjà normalisé (minuscules, sans
accents) : la requête suit la même normalisation.

Ordre des résultats : références exactes (codes, numéros, expressions entre guillemets),
puis plein texte (bm25), puis — seulement si le plein texte ne trouve rien — trigrammes.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata

PLAFOND = 200_000
SEUIL_TRIGRAMMES = 0.4
LONGUEUR_EXTRAIT = 280
TERMES_MAX = 32
LIMITE_MAX = 50

# Guillemets typographiques écrits en échappements (U+201C / U+201D) : une copie les
# transformerait silencieusement en guillemets droits.
_GUILLEMETS = re.compile('"([^"]+)"|«\\s*([^»]+?)\\s*»|\u201c([^\u201d]+)\u201d')
_CARACTERES_REFERENCE = set("-_./@#")
_BORDS = ".,;:!?()[]{}'\"«»\u201c\u201d…"


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", (texte or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def creer_tables(con: sqlite3.Connection) -> None:
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents_recherche USING fts5("
                "doc_id UNINDEXED, nom, texte, tokenize='unicode61 remove_diacritics 2')")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS documents_trigrammes USING fts5("
                "doc_id UNINDEXED, texte, tokenize='trigram')")


def _texte_indexe(ligne) -> tuple[str, str]:
    meta = json.loads(ligne["metadonnees"] or "{}")
    c = meta.get("classement") or {}
    morceaux = [ligne["texte_extrait"] or "", c.get("categorie") or "", " ".join(c.get("tags") or []),
                c.get("projet") or "", c.get("resume") or "", c.get("entreprise_nom") or ""]
    return normaliser(ligne["nom"] or ""), normaliser(" ".join(m for m in morceaux if m))[:PLAFOND]


def desindexer(con: sqlite3.Connection, doc_id: str) -> None:
    con.execute("DELETE FROM documents_recherche WHERE doc_id = ?", (doc_id,))
    con.execute("DELETE FROM documents_trigrammes WHERE doc_id = ?", (doc_id,))


def indexer(con: sqlite3.Connection, doc_id: str) -> None:
    desindexer(con, doc_id)
    ligne = con.execute("SELECT nom, texte_extrait, metadonnees FROM documents WHERE id = ?",
                        (doc_id,)).fetchone()
    if ligne is None:
        return
    nom, texte = _texte_indexe(ligne)
    con.execute("INSERT INTO documents_recherche (doc_id, nom, texte) VALUES (?, ?, ?)", (doc_id, nom, texte))
    con.execute("INSERT INTO documents_trigrammes (doc_id, texte) VALUES (?, ?)", (doc_id, f"{nom} {texte}"))


def reconstruire_index(con: sqlite3.Connection) -> int:
    con.execute("DELETE FROM documents_recherche")
    con.execute("DELETE FROM documents_trigrammes")
    ids = [r[0] for r in con.execute("SELECT id FROM documents").fetchall()]
    for doc_id in ids:
        indexer(con, doc_id)
    return len(ids)


def index_desynchronise(con: sqlite3.Connection) -> bool:
    n = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("documents", "documents_recherche", "documents_trigrammes")]
    return not (n[0] == n[1] == n[2])


# ── Recherche ───────────────────────────────────────────────────────────────────

def _est_reference(jeton: str) -> bool:
    return (len(jeton) >= 2 and any(c.isalnum() for c in jeton)
            and (any(c.isdigit() for c in jeton) or any(c in _CARACTERES_REFERENCE for c in jeton)))


def extraire_references(requete: str) -> list[str]:
    """Mêmes règles que la Mémoire (S238) et la Forge (S241)."""
    candidates = []
    for m in _GUILLEMETS.finditer(requete):
        expression = " ".join(next(g for g in m.groups() if g).split())
        if expression:
            candidates.append(expression)
    for jeton in _GUILLEMETS.sub(" ", requete).split():
        jeton = jeton.strip(_BORDS)
        if _est_reference(jeton):
            candidates.append(jeton)
    vues, references = set(), []
    for c in candidates:
        if c.casefold() not in vues:
            vues.add(c.casefold())
            references.append(c)
    return references[:10]


def _motif(reference_normalisee: str) -> str:
    morceaux = [re.escape(m) for m in reference_normalisee.split()]
    return r"(?<![a-z0-9])" + r"\s+".join(morceaux) + r"(?![a-z0-9])"


def _regexp(motif: str, texte: str | None) -> bool:
    return texte is not None and re.search(motif, texte) is not None


def _termes(requete: str) -> list[str]:
    return re.findall(r"[^\W_]+", normaliser(requete))[:TERMES_MAX]


def _expression_fts(jetons: list[str]) -> str:
    return " OR ".join('"' + j.replace('"', '""') + '"' for j in jetons)


def _trigrammes_de(mot: str) -> set[str]:
    return {mot[i:i + 3] for i in range(len(mot) - 2)}


def _exacts(con, requete: str) -> list[str]:
    trouves: dict[str, tuple[int, bool]] = {}
    for reference in (normaliser(r) for r in extraire_references(requete)):
        motif = _motif(reference)
        for doc_id, nom in con.execute(
            "SELECT doc_id, nom FROM documents_recherche WHERE (nom || ' ' || texte) REGEXP ?", (motif,)
        ).fetchall():
            n, titre = trouves.get(doc_id, (0, False))
            trouves[doc_id] = (n + 1, titre or re.search(motif, nom) is not None)
    return sorted(trouves, key=lambda d: (-trouves[d][0], not trouves[d][1], d))


def _plein_texte(con, mots: list[str], limite: int) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT doc_id FROM documents_recherche WHERE documents_recherche MATCH ? "
        "ORDER BY bm25(documents_recherche, 0.0, 5.0, 1.0), doc_id LIMIT ?",
        (_expression_fts(mots), limite)).fetchall()]


def _par_trigrammes(con, mots: list[str], limite: int) -> list[str]:
    longs = [m for m in mots if len(m) >= 3]
    if not longs:
        return []
    tous = sorted(set().union(*(_trigrammes_de(m) for m in longs)))
    candidats = con.execute(
        "SELECT doc_id, texte FROM documents_trigrammes WHERE documents_trigrammes MATCH ? "
        "ORDER BY bm25(documents_trigrammes) LIMIT ?", (_expression_fts(tous), limite * 4)).fetchall()
    gardes = []
    for doc_id, texte in candidats:
        # Part des trigrammes du mot le mieux retrouvé (proche de word_similarity, S238).
        part = max(sum(1 for t in _trigrammes_de(m) if t in texte) / len(_trigrammes_de(m)) for m in longs)
        if part >= SEUIL_TRIGRAMMES:
            gardes.append((part, doc_id))
    gardes.sort(key=lambda x: (-x[0], x[1]))
    return [d for _, d in gardes][:limite]


def _extrait(texte: str, mots: list[str]) -> str:
    texte = " ".join((texte or "").split())
    if len(texte) <= LONGUEUR_EXTRAIT:
        return texte
    normalise = normaliser(texte)
    positions = [p for p in (normalise.find(m) for m in mots) if p >= 0]
    debut = max(0, min(positions) - LONGUEUR_EXTRAIT // 3) if positions else 0
    debut = min(debut, len(texte) - LONGUEUR_EXTRAIT)
    return (("…" if debut > 0 else "") + texte[debut:debut + LONGUEUR_EXTRAIT]
            + ("…" if debut + LONGUEUR_EXTRAIT < len(texte) else ""))


def chercher(con: sqlite3.Connection, requete: str, limite: int = 10) -> list[dict]:
    requete = (requete or "").strip()
    if not requete:
        return []
    limite = min(max(int(limite), 1), LIMITE_MAX)
    con.create_function("regexp", 2, _regexp, deterministic=True)
    exacts = _exacts(con, requete)
    mots = _termes(requete)
    lexical: list[str] = []
    if mots:
        lexical = _plein_texte(con, mots, limite * 3) or _par_trigrammes(con, mots, limite * 3)
    ordre = exacts + [d for d in lexical if d not in exacts]
    resultats = []
    for doc_id in ordre[:limite]:
        ligne = con.execute("SELECT nom, texte_extrait FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if ligne is None:
            continue
        resultats.append({"id": doc_id, "source": "ingestion", "titre": ligne["nom"],
                          "extrait": _extrait(ligne["texte_extrait"] or "", mots),
                          "rang": len(resultats) + 1, "exact": doc_id in exacts})
    return resultats
