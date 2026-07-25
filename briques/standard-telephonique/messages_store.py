"""Persistance SQLite des messages vocaux reçus par le répondeur (stdlib uniquement)."""
import sqlite3
from pathlib import Path


def _connexion(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option TEXT,
            audio_path TEXT NOT NULL,
            duree_s REAL NOT NULL,
            texte TEXT,
            horodatage TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    return conn


def enregistrer(db_path: str, *, option: str | None, audio_path: str, duree_s: float,
                texte: str | None) -> int:
    """Enregistre un message reçu, retourne son id."""
    conn = _connexion(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO messages (option, audio_path, duree_s, texte) VALUES (?, ?, ?, ?)",
            (option, audio_path, duree_s, texte),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def lister(db_path: str, limite: int = 20) -> list[dict]:
    """Liste les messages, les plus récents d'abord. Liste vide si la DB n'existe pas
    encore (repli honnête — pas une erreur, juste « aucun message pour l'instant »)."""
    if not Path(db_path).exists():
        return []
    conn = _connexion(db_path)
    try:
        rows = conn.execute(
            "SELECT id, option, audio_path, duree_s, texte, horodatage "
            "FROM messages ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
        return [
            {
                "id": r[0], "option": r[1], "audio_path": r[2],
                "duree_s": r[3], "texte": r[4], "horodatage": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()
