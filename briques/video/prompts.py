"""Construction de PROMPTS VIDÉO à partir d'épisodes / de fiches de personnages.

Cœur de la SYNERGIE (miroir de prompts.py de la brique images) : un épisode (titre +
synopsis) devient un prompt de BANDE-ANNONCE ; une fiche venue de la brique Personnages
(nom, rôle, description, empreinte holistique) devient un prompt d'ANIMATION cohérent.
Fonctions PURES (testables sans moteur ni réseau) : on sépare « décrire le mouvement »
(ici) de « rendre la vidéo » (moteur.py / fournisseurs hébergés).
"""
import re

# Suffixes de style par défaut, orientés MOUVEMENT (ce qui distingue la vidéo de l'image).
STYLE_TEASER = ("cinematic teaser trailer, dynamic camera movement, dramatic lighting, "
                "atmospheric, film grain, smooth motion, high detail")
STYLE_ANIMATION = ("subtle natural motion, breathing, gentle head movement, blinking, "
                   "soft ambient light, shallow depth of field, cinematic portrait")

# ── Traits visuels dérivés de l'empreinte holistique (tags → descripteurs) ──
# Réutilise le vocabulaire de la brique images, ajouté d'une nuance de MOUVEMENT.
_TRAITS = {
    "feu":      "warm fiery palette, flickering ember light",
    "eau":      "cool blue palette, flowing fabrics, rippling reflections",
    "terre":    "earthy tones, grounded steady presence",
    "air":      "airy pale palette, windswept hair, drifting motion",
    "solaire":  "radiant golden light, confident bearing",
    "lunaire":  "soft silver moonlight, dreamy mysterious mood",
    "lumiere":  "luminous highlights, hopeful expression",
    "ombre":    "deep shadows, brooding chiaroscuro",
    "noble":    "regal bearing, refined attire",
    "sauvage":  "untamed look, rugged details",
    "mystique": "esoteric symbols, arcane atmosphere",
    "guerrier": "battle-worn armor, determined stance",
    "sage":     "wise serene expression, scholarly attire",
}


def _nettoyer(txt) -> str:
    return re.sub(r"\s+", " ", str(txt or "").strip())


def _traits_de(empreinte) -> list:
    """Descripteurs visuels issus des tags/éléments d'une empreinte (liste ou dict)."""
    if not empreinte:
        return []
    if isinstance(empreinte, dict):
        mots = []
        for v in empreinte.values():
            mots += re.findall(r"[a-zàâäéèêëïîôöùûüç]+", str(v).lower())
    else:
        mots = re.findall(r"[a-zàâäéèêëïîôöùûüç]+", " ".join(map(str, empreinte)).lower())
    vus, out = set(), []
    for m in mots:
        d = _TRAITS.get(m)
        if d and d not in vus:
            vus.add(d)
            out.append(d)
    return out


def prompt_teaser(titre: str = "", synopsis: str = "", style: str = "",
                  personnages=None) -> dict:
    """Titre + synopsis (+ personnages) → {prompt} pour une BANDE-ANNONCE (Studio→Vidéo)."""
    bouts = []
    if _nettoyer(titre):
        bouts.append(_nettoyer(titre))
    if _nettoyer(synopsis):
        bouts.append(_nettoyer(synopsis)[:300])
    noms = [_nettoyer(p.get("nom") if isinstance(p, dict) else p) for p in (personnages or [])]
    noms = [n for n in noms if n][:4]
    if noms:
        bouts.append("featuring " + ", ".join(noms))
    bouts.append(_nettoyer(style) or STYLE_TEASER)
    return {"prompt": ", ".join(b for b in bouts if b)}


def prompt_animation(fiche: dict, style: str = "") -> dict:
    """Fiche personnage → {prompt} pour ANIMER un portrait (Personnages→Vidéo).

    Champs lus (tous facultatifs sauf un identifiant) : nom, role, description,
    archetype, ambiance, empreinte (tags/éléments holistiques), style."""
    fiche = fiche or {}
    nom = _nettoyer(fiche.get("nom") or fiche.get("prenoms"))
    bouts = [f"animated portrait of {nom}" if nom else "animated character portrait"]
    if _nettoyer(fiche.get("role")):
        bouts.append(_nettoyer(fiche["role"]))
    if _nettoyer(fiche.get("archetype")):
        bouts.append(f"archetype: {_nettoyer(fiche['archetype'])}")
    if _nettoyer(fiche.get("description")):
        bouts.append(_nettoyer(fiche["description"]))
    bouts += _traits_de(fiche.get("empreinte") or fiche.get("tags"))
    if _nettoyer(fiche.get("ambiance")):
        bouts.append(_nettoyer(fiche["ambiance"]))
    bouts.append(_nettoyer(style) or _nettoyer(fiche.get("style")) or STYLE_ANIMATION)
    return {"prompt": ", ".join(b for b in bouts if b)}
