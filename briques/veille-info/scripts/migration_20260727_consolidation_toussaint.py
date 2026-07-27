"""Migration ponctuelle (2026-07-27) : consolide sous le VRAI compte web de Toussaint les
sources RSS éparpillées sur 3 tenants distincts de veille-info, constaté en prod (HP,
docker exec workplace_veille_info, /data/veille_info.db) :

- `perso:Toussaint` (5 sources cosmétique, ids 12-16) : bucket créé HORS du parcours
  Keycloak (probablement des données de test/seed ajoutées via curl), jamais atteint par
  la vraie session web de Toussaint.
- `public` (1 source, id 8, TechCrunch AI) : tenant anonyme (aucune clé API présentée),
  conséquence du trou d'isolation d'atelier-veille corrigé par ailleurs (cf.
  docs/superpowers/plans/2026-07-27-atelier-veille-isolation-multiuser.md).
- `perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e` (9 sources IA déjà en place, ids 2-7/9-11) :
  le VRAI compte web de Toussaint — son `sub` Keycloak (cf. core/auth.py::
  sub_session_optionnel). C'est la cible de consolidation.

Ne touche QUE la table `sources` — volontairement, pas `articles`/`digests` : ces derniers
n'ont aucune clé étrangère depuis `sources`, l'historique des anciens digests reste
orphelin mais inoffensif ; les FUTURS digests seront correctement rattachés puisque les
sources pointeront désormais toutes vers la cible.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

CIBLE = "perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e"

_IDS_COSMETIQUE = (12, 13, 14, 15, 16)
_ID_TECHCRUNCH = 8


def migrer(conn: sqlite3.Connection, *, dry_run: bool = False) -> dict:
    """Applique la consolidation. Ne commite/rollback JAMAIS elle-même — laisse l'appelant
    (CLI ci-dessous, ou un test) décider. Idempotente : sur une base déjà migrée, les
    clauses WHERE ne matchent plus rien → tous les compteurs à 0."""
    c = conn.cursor()

    c.execute(
        f"UPDATE sources SET user_id = ?, thematique = 'Cosmétique' "
        f"WHERE id IN ({','.join('?' * len(_IDS_COSMETIQUE))}) AND user_id = 'perso:Toussaint'",
        (CIBLE, *_IDS_COSMETIQUE))
    cosmetique_migrees = c.rowcount

    c.execute(
        "UPDATE sources SET user_id = ?, thematique = 'IA' "
        "WHERE id = ? AND user_id = 'public'",
        (CIBLE, _ID_TECHCRUNCH))
    techcrunch_migree = c.rowcount

    c.execute(
        "UPDATE sources SET thematique = 'IA' WHERE user_id = ? AND thematique = ''",
        (CIBLE,))
    ia_retaguees = c.rowcount

    return {
        "cosmetique_migrees": cosmetique_migrees,
        "techcrunch_migree": techcrunch_migree,
        "ia_retaguees": ia_retaguees,
    }


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/data/veille_info.db",
                        help="Chemin de la base SQLite (défaut : /data/veille_info.db, "
                             "le chemin DANS le conteneur workplace_veille_info).")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'applique rien : affiche ce qui SERAIT fait puis ROLLBACK.")
    args = parser.parse_args()

    if not Path(args.db).exists():
        raise SystemExit(f"Base introuvable : {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        resultat = migrer(conn, dry_run=args.dry_run)
        print(f"cosmetique_migrees={resultat['cosmetique_migrees']} "
             f"techcrunch_migree={resultat['techcrunch_migree']} "
             f"ia_retaguees={resultat['ia_retaguees']}")
        if args.dry_run:
            print("--dry-run : ROLLBACK (rien n'a été écrit).")
            conn.rollback()
        else:
            conn.commit()
            print("COMMIT effectué.")
    finally:
        conn.close()


if __name__ == "__main__":
    _cli()
