"""Enrichissement OPT-IN d'une entreprise — le module RGPD-prudent de la brique geo.

Le cahier des charges GeoHub demandait du « scraping d'emails ». L'API Sirene ne les
fournit pas EXPRÈS (RGPD) ; les moissonner en masse recréerait le problème. Choix
(consigné dans l'ADR 2026-07-06-geo-sqlite-rtree.md) :
  • **opt-in, à la demande** : une entreprise À LA FOIS, jamais de passe massive ;
  • **sourcé** : uniquement ce que l'entreprise AFFICHE ELLE-MÊME sur son site officiel
    (trouvé via la brique `recherche`, souveraine) — jamais d'annuaires tiers ;
  • **journalisé** : chaque tentative laisse une trace consultable (`/enrichissements`).

Découpage : heuristiques PURES (extraction, choix du site) testables hors-ligne ;
l'I/O passe par la brique recherche (`/rechercher` puis `/lire-page`)."""
from __future__ import annotations

import os
import re
import unicodedata
from urllib.parse import urlparse

import httpx

# Annuaires/plateformes : jamais retenus comme « site officiel » (on n'y gratte rien).
DOMAINES_ANNUAIRES = {
    "pagesjaunes.fr", "societe.com", "pappers.fr", "annuaire-entreprises.data.gouv.fr",
    "infogreffe.fr", "verif.com", "kompass.com", "manageo.fr", "bilansgratuits.fr",
    "linkedin.com", "facebook.com", "instagram.com", "wikipedia.org",
    "tripadvisor.fr", "tripadvisor.com", "thefork.fr", "lafourchette.com",
    "ubereats.com", "deliveroo.fr", "leboncoin.fr", "yelp.fr", "yelp.com",
    "google.com", "google.fr", "mappy.com", "petitfute.com",
}
_MOTS_VIDES = {"sarl", "sas", "sasu", "eurl", "sci", "les", "des", "chez", "the", "et"}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_TEL_RE = re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.\-]?\d{2}){4}")


# ── Heuristiques pures ───────────────────────────────────────────
def extraire_contacts(texte: str) -> dict:
    """Emails + téléphones FR AFFICHÉS dans un texte de page. Dédupliqués, ordre
    d'apparition ; écarte les faux positifs usuels (fichiers image, no-reply)."""
    emails = []
    for e in _EMAIL_RE.findall(texte or ""):
        e = e.lower().strip(".")
        if e.rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "svg", "webp"):
            continue
        if "noreply" in e or "no-reply" in e or "sentry" in e or "example" in e:
            continue
        if e not in emails:
            emails.append(e)
    tels = []
    for t in _TEL_RE.findall(texte or ""):
        t = re.sub(r"[\s.\-]", " ", t).strip()
        if t not in tels:
            tels.append(t)
    return {"emails": emails, "telephones": tels}


def _normaliser(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower())


def _domaine(url: str) -> str:
    hote = (urlparse(url).netloc or "").lower()
    return hote.removeprefix("www.")


def choisir_site(resultats: list[dict], nom: str) -> str | None:
    """Le SITE OFFICIEL probable parmi les résultats de recherche : premier lien qui
    n'est PAS un annuaire/plateforme et dont le titre ou le domaine porte un mot
    significatif du nom de l'entreprise. None si rien de convaincant — honnête."""
    jetons = [j for j in _normaliser(nom).split()
              if len(j) >= 3 and j not in _MOTS_VIDES]
    if not jetons:
        return None
    for r in resultats or []:
        url = r.get("url") or ""
        if not url or _domaine(url) in DOMAINES_ANNUAIRES:
            continue
        botte = _normaliser((r.get("titre") or "") + " " + url)
        if any(j in botte for j in jetons):
            return url
    return None


def trouver_lien_contact(liens: list) -> str | None:
    """Premier lien « contact » d'une page (les emails vivent souvent là)."""
    for lien in liens or []:
        url = lien if isinstance(lien, str) else (lien.get("url") or "")
        texte = "" if isinstance(lien, str) else (lien.get("texte") or "")
        if "contact" in url.lower() or "contact" in texte.lower():
            return url
    return None


# ── I/O : via la brique recherche (souveraine) ───────────────────
def _base_recherche() -> str:
    return os.getenv("RECHERCHE_URL", "http://host.docker.internal:6040").rstrip("/")


def _entetes() -> dict:
    cle = os.getenv("RECHERCHE_KEY", "")
    return {"X-API-Key": cle} if cle else {}


def enrichir(objet: dict) -> dict:
    """Tente d'enrichir UN objet : recherche du site officiel, lecture de la page
    (puis de sa page contact si besoin), extraction des coordonnées publiques.
    Renvoie un rapport honnête ({statut: ok | introuvable | impossible}) ; lève
    httpx.HTTPError si la brique recherche est injoignable (le caller journalise)."""
    meta = objet.get("metadata") or {}
    nom = meta.get("nom") or ""
    if not nom:
        return {"statut": "impossible", "detail": "Objet sans nom : rien à chercher."}
    requete = " ".join(x for x in (nom, meta.get("commune") or "") if x)
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{_base_recherche()}/rechercher",
                        json={"requete": requete, "n": 8}, headers=_entetes())
        r.raise_for_status()
        site = choisir_site(r.json().get("resultats", []), nom)
        if not site:
            return {"statut": "introuvable", "requete": requete,
                    "detail": "Aucun site officiel identifié (annuaires écartés)."}
        rapport = {"statut": "ok", "requete": requete, "site": site,
                   "emails": [], "telephones": [], "source_url": site}
        page = client.post(f"{_base_recherche()}/lire-page",
                           json={"url": site}, headers=_entetes())
        if page.status_code < 400:
            d = page.json()
            contacts = extraire_contacts(d.get("texte") or "")
            rapport["emails"] = contacts["emails"]
            rapport["telephones"] = contacts["telephones"]
            if not rapport["emails"]:
                lien = trouver_lien_contact(d.get("liens") or [])
                if lien:
                    p2 = client.post(f"{_base_recherche()}/lire-page",
                                     json={"url": lien}, headers=_entetes())
                    if p2.status_code < 400:
                        c2 = extraire_contacts(p2.json().get("texte") or "")
                        if c2["emails"]:
                            rapport["emails"] = c2["emails"]
                            rapport["source_url"] = lien
                        rapport["telephones"] = list(dict.fromkeys(
                            rapport["telephones"] + c2["telephones"]))
        return rapport
