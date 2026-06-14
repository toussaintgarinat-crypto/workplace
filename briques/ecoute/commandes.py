"""Commandes de noms d'éveil sur mesure (S43) — le **palier payant**.

Un client veut son **nom de marque** comme mot d'éveil (« Dis, Acme… ») ? openWakeWord
exige *un modèle entraîné par nom* (pas de zero-shot, cf. POC S41/DECISION). On vend
donc un cycle :

    en_attente_paiement → payee → en_entrainement → livree
                                              └────────→ echec

- **en_attente_paiement** : commande créée, lien Stripe émis (cf. `paiement.py`).
- **payee** : webhook Stripe signé reçu (ou règlement mock honnête) → entre en file.
- **en_entrainement** : l'**horloge S29** a pris la commande (file d'attente, ~1 h).
- **livree** : le modèle ONNX est installé → le nom devient sélectionnable sur le WS.
- **echec** : l'entraînement a échoué (tracé, le client n'est pas débité dans le vide).

Ce module sépare comme S42 :
  • la **logique de transition** (`prochain_etat`, `slugifier`) = pure, testable ;
  • le **magasin** (`MagasinCommandes`) = un side-car SQLite (même motif que l'horloge
    `core/horloge.py` : pas de Redis, pas de broker), qui sérialise les états et garantit
    l'idempotence (re-commander une marque déjà en cours rend la commande existante).

L'**entraînement lui-même** vit dans `entrainement.py` (entraîneur pluggable, honnête).
"""
from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
import uuid as uuidlib
from datetime import datetime
from pathlib import Path

DB = os.getenv("COMMANDES_DB", "/data/ecoute.db")
PRIX_CENTS = int(os.getenv("WAKEWORD_PRIX_CENTS", "4900"))   # 49,00 € par défaut
DEVISE = os.getenv("WAKEWORD_DEVISE", "eur")

# États du cycle de vie (ordre = progression normale ; `echec` est une sortie latérale).
ETATS = ("en_attente_paiement", "payee", "en_entrainement", "livree", "echec")
_TERMINAUX = {"livree", "echec"}

# Transitions autorisées (le reste est refusé → pas de saut d'état incohérent).
_TRANSITIONS = {
    "en_attente_paiement": {"payee", "echec"},
    "payee": {"en_entrainement", "echec"},
    "en_entrainement": {"livree", "echec"},
    "livree": set(),
    "echec": set(),
}


def slugifier(nom: str) -> str:
    """« Maison Léon ! » → « maison_leon ». Identifiant sûr pour le fichier ONNX ET la clé
    de prédiction openWakeWord (le *stem* du fichier). Produit FR-first : on **translittère**
    les accents (é→e, ç→c) au lieu de les jeter — sinon « Léon » deviendrait « l_on » et
    deux graphies de la même marque casseraient l'idempotence. Vide si rien d'exploitable."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFKD", nom) if not unicodedata.combining(c)
    )
    base = re.sub(r"[^a-z0-9]+", "_", sans_accents.lower()).strip("_")
    return base[:40]


def transition_permise(actuel: str, cible: str) -> bool:
    """Pure : la transition `actuel → cible` est-elle autorisée par la machine d'états ?"""
    return cible in _TRANSITIONS.get(actuel, set())


def prochain_etat(actuel: str) -> str | None:
    """Pure : étape *nominale* suivante (paiement→file→entraînement→livraison), ou None
    si terminal. Sert à la file d'entraînement pour avancer une commande payée."""
    nominal = {
        "en_attente_paiement": "payee",
        "payee": "en_entrainement",
        "en_entrainement": "livree",
    }
    return nominal.get(actuel)


def _conn() -> sqlite3.Connection:
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


class MagasinCommandes:
    """Persistance SQLite des commandes (side-car, comme le journal de l'horloge)."""

    def __init__(self, db: str | None = None):
        self.db = db or DB

    def _c(self) -> sqlite3.Connection:
        Path(self.db).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        return c

    def init_db(self) -> None:
        with self._c() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS commandes (
                    id            TEXT PRIMARY KEY,
                    nom_marque    TEXT NOT NULL,
                    modele        TEXT NOT NULL,       -- slug = stem du fichier ONNX livré
                    statut        TEXT NOT NULL,
                    prix_cents    INTEGER NOT NULL,
                    devise        TEXT NOT NULL,
                    stripe_session_id TEXT,
                    factice       INTEGER DEFAULT 0,   -- 1 = modèle stand-in (pas un vrai entraînement GPU)
                    relances      INTEGER DEFAULT 0,
                    message       TEXT,
                    cree_le       TEXT NOT NULL,
                    maj_le        TEXT NOT NULL
                )
            """)

    # ── Lecture ──────────────────────────────────────────────────────────────

    def get(self, cid: str) -> dict | None:
        with self._c() as c:
            row = c.execute("SELECT * FROM commandes WHERE id = ?", (cid,)).fetchone()
        return dict(row) if row else None

    def par_session(self, session_id: str) -> dict | None:
        with self._c() as c:
            row = c.execute(
                "SELECT * FROM commandes WHERE stripe_session_id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def lister(self, statut: str | None = None) -> list[dict]:
        with self._c() as c:
            if statut:
                rows = c.execute(
                    "SELECT * FROM commandes WHERE statut = ? ORDER BY cree_le", (statut,)
                ).fetchall()
            else:
                rows = c.execute("SELECT * FROM commandes ORDER BY cree_le").fetchall()
        return [dict(r) for r in rows]

    def _en_cours_pour_marque(self, modele: str) -> dict | None:
        """Une commande NON terminale pour ce slug (idempotence : pas de doublon)."""
        with self._c() as c:
            row = c.execute(
                "SELECT * FROM commandes WHERE modele = ? AND statut NOT IN ('livree','echec') "
                "ORDER BY cree_le DESC LIMIT 1",
                (modele,),
            ).fetchone()
        return dict(row) if row else None

    def livrees(self) -> list[dict]:
        """Noms sur mesure déjà livrés (= sélectionnables en plus du catalogue gratuit)."""
        return self.lister("livree")

    # ── Écriture ─────────────────────────────────────────────────────────────

    def creer(self, nom_marque: str) -> dict:
        """Crée une commande `en_attente_paiement`. **Idempotent** : si une commande
        non terminale existe déjà pour cette marque, on la rend (pas de double-débit)."""
        self.init_db()
        slug = slugifier(nom_marque)
        if not slug:
            raise ValueError("Nom de marque vide ou non prononçable.")
        existante = self._en_cours_pour_marque(slug)
        if existante:
            return existante
        maintenant = datetime.utcnow().isoformat()
        cid = str(uuidlib.uuid4())
        with self._c() as c:
            c.execute(
                "INSERT INTO commandes (id, nom_marque, modele, statut, prix_cents, devise, "
                "stripe_session_id, factice, relances, message, cree_le, maj_le) "
                "VALUES (?,?,?,?,?,?,?,0,0,?,?,?)",
                (cid, nom_marque, slug, "en_attente_paiement", PRIX_CENTS, DEVISE,
                 None, None, maintenant, maintenant),
            )
        return self.get(cid)

    def _maj(self, cid: str, **champs) -> dict | None:
        champs["maj_le"] = datetime.utcnow().isoformat()
        cols = ", ".join(f"{k} = ?" for k in champs)
        with self._c() as c:
            c.execute(f"UPDATE commandes SET {cols} WHERE id = ?",
                      (*champs.values(), cid))
        return self.get(cid)

    def attacher_session(self, cid: str, session_id: str) -> dict | None:
        return self._maj(cid, stripe_session_id=session_id)

    def changer_etat(self, cid: str, cible: str, *, message: str | None = None,
                     factice: bool | None = None) -> dict:
        """Transition gardée : refuse un saut d'état incohérent (idempotent si déjà sur
        la cible). Lève `ValueError` sur une transition interdite."""
        c = self.get(cid)
        if not c:
            raise KeyError(cid)
        actuel = c["statut"]
        if actuel == cible:
            return c  # idempotent
        if not transition_permise(actuel, cible):
            raise ValueError(f"Transition interdite {actuel} → {cible}")
        champs = {"statut": cible}
        if message is not None:
            champs["message"] = message
        if factice is not None:
            champs["factice"] = 1 if factice else 0
        return self._maj(cid, **champs)

    def marquer_payee(self, cid: str) -> dict:
        """Idempotent : déjà payée/plus loin → on ne régresse pas, on rend l'état."""
        c = self.get(cid)
        if not c:
            raise KeyError(cid)
        if c["statut"] != "en_attente_paiement":
            return c  # déjà payée ou plus avancée : pas de double-traitement
        return self.changer_etat(cid, "payee")

    def incr_relance(self, cid: str) -> dict | None:
        c = self.get(cid)
        if not c:
            return None
        return self._maj(cid, relances=(c["relances"] or 0) + 1)


def vue(c: dict) -> dict:
    """Projection publique d'une commande (jamais d'interne brut hors contexte)."""
    return {
        "id": c["id"],
        "nom_marque": c["nom_marque"],
        "modele": c["modele"],
        "statut": c["statut"],
        "prix_cents": c["prix_cents"],
        "devise": c["devise"],
        "factice": bool(c.get("factice")),
        "relances": c.get("relances", 0),
        "message": c.get("message"),
        "cree_le": c["cree_le"],
        "maj_le": c["maj_le"],
        "terminal": c["statut"] in _TERMINAUX,
    }
