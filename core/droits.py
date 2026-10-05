"""Outils réservés à l'admin du cerveau (revue S240, C-B).

Le chat de l'assistant répond SANS session (Telegram, Mini App, appareils du LAN/mesh). Ses
outils ordinaires restent ouverts à ces surfaces ; ceux qui écrivent du code, exécutent,
fusionnent, restaurent des bases ou changent le prompt système ne s'exécutent que si le TOUR
porte une session admin du cerveau (`auth.admin_cerveau_ou_none`, mêmes règles que les
routes de ⚙ Cerveau : session, `CERVEAU_ADMINS`, anti-CSRF).

Le droit vit dans un ContextVar posé par /assistant/chat pour le tour (défaut : faux).
Le co-agent autonome (pouls, horloge) et /mcp ne le posent jamais : décision S240, une clé
`MCP_KEY` authentifie un CLIENT, pas un humain admin présent — elle ne vaut pas admin.
"""
from contextvars import ContextVar

ADMIN_CERVEAU: ContextVar[bool] = ContextVar("admin_cerveau", default=False)

# Toute la brique dev : elle monte le dépôt (donc le .env) en écriture et le socket Docker.
# Même ses lectures (`dev_ide_lire_fichier`) exposeraient les secrets du dépôt.
PREFIXES_RESERVES = ("dev_",)

RESERVES = frozenset({
    # Sauvegarde : restaurer écrase toutes les bases ; lancer écrase l'instantané précédent.
    "sauvegarde_usb_restaurer", "sauvegarde_usb_lancer",
    # Auto-amélioration : un addendum appliqué entre dans le prompt système (S69/S70).
    "amelioration_decider", "capacite_decider", "curateur_lancer",
})


def est_reserve_admin(nom: str) -> bool:
    return nom in RESERVES or nom.startswith(PREFIXES_RESERVES)


def refus(nom: str) -> str:
    """Message pour le LLM : clair, et qui lui dit quoi répondre à l'humain."""
    import json
    return json.dumps({
        "ok": False,
        "erreur": (f"« {nom} » est réservé à l'admin du cerveau : il faut être connecté au "
                   "tableau de bord du Cœur avec un compte admin (⚙ Cerveau). Depuis Telegram, "
                   "la Mini App, /mcp ou une tâche autonome, cette action est refusée."),
    }, ensure_ascii=False)
