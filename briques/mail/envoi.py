"""Envoi d'une réponse par SMTP (v0.2.0) — l'étape qui agit sur le monde réel.

Honnêteté STRICTE :
  • Compte IMAP réel connecté → envoi **réel** via `smtplib` (STARTTLS), depuis l'adresse de ce
    compte, avec les en-têtes de fil (In-Reply-To/References) pour que la réponse s'attache bien.
  • Pas de compte réel (boîte mock / brouillon issu d'un message simulé) → envoi **SIMULÉ**,
    clairement étiqueté `mode="simule"` : AUCUN email ne part. On ne fait jamais croire qu'un
    message simulé a été envoyé pour de vrai.

L'envoi est une action à effet de bord irréversible : la décision (le « valide et envoie ») reste
humaine — la brique ne fait qu'exécuter un envoi explicitement demandé. Le mot de passe d'app n'est
jamais loggé ni renvoyé.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage


def serveur_smtp(compte: dict) -> tuple[str, int]:
    """(hôte, port) SMTP du compte. Utilise les valeurs stockées, sinon les devine depuis l'hôte
    IMAP (imap.example.com → smtp.example.com), port 587 (STARTTLS) par défaut."""
    host = (compte.get("smtp_host") or "").strip()
    port = int(compte.get("smtp_port") or 0)
    if not host:
        imap = (compte.get("host") or "").strip()
        host = ("smtp." + imap[len("imap."):]) if imap.startswith("imap.") else imap
    return host, (port or 587)


def _construire(de: str, a: str, sujet: str, corps: str, en_reponse_a_uid: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = de
    msg["To"] = a
    msg["Subject"] = sujet
    if en_reponse_a_uid:
        # Rattache la réponse au fil. Les UID IMAP ne sont pas des Message-ID, mais c'est mieux
        # que rien et inoffensif si le serveur ne s'en sert pas.
        msg["In-Reply-To"] = en_reponse_a_uid
        msg["References"] = en_reponse_a_uid
    msg.set_content(corps)
    return msg


def envoyer(compte: dict | None, *, a: str, sujet: str, corps: str,
            en_reponse_a_uid: str = "") -> dict:
    """Envoie la réponse. Renvoie {envoye, mode:"reel"|"simule", de, message}.

    `compte` (avec `mot_de_passe` déchiffré) → envoi réel ; None → envoi simulé honnête.
    Lève `RuntimeError` si l'envoi réel échoue (l'appelant transforme en erreur HTTP propre)."""
    if not a:
        raise RuntimeError("Pas de destinataire pour ce brouillon.")
    if compte is None:
        return {"envoye": True, "mode": "simule", "de": "simulé",
                "message": "Envoi SIMULÉ (boîte mock) : aucun email réel n'a été envoyé."}

    de = compte["utilisateur"]
    host, port = serveur_smtp(compte)
    msg = _construire(de, a, sujet, corps, en_reponse_a_uid)
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.login(de, compte["mot_de_passe"])
            s.send_message(msg)
    except Exception as e:  # noqa: BLE001 — on n'expose jamais le mot de passe / la trace brute
        raise RuntimeError(f"Envoi SMTP refusé via {host}:{port} "
                           "(vérifie le serveur SMTP et le mot de passe d'application).") from e
    return {"envoye": True, "mode": "reel", "de": de,
            "message": f"Réponse envoyée à {a} depuis {de}."}
