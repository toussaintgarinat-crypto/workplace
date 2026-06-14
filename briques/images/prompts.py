"""Construction de PROMPTS VISUELS à partir des fiches de personnages / d'épisodes.

C'est le cœur de la SYNERGIE : une fiche venue de la brique Personnages (nom, rôle,
description, et — si dispo — son empreinte holistique : archétype, éléments, ambiance)
devient un prompt d'image cohérent. Fonctions PURES (testables sans moteur ni réseau) :
on sépare « décrire quoi peindre » (ici) de « peindre » (moteur.py / ComfyUI).
"""
import re

# Suffixe de style par défaut (look « concept art » lisible, neutre).
STYLE_DEFAUT = ("character concept art, digital painting, highly detailed, "
                "dramatic cinematic lighting, soft focus background")
STYLE_COUVERTURE = ("cover illustration, cinematic key art, dramatic composition, "
                    "rich atmosphere, highly detailed, professional digital painting")

# Négatif générique : ce qu'on ne veut jamais voir.
NEGATIF_DEFAUT = ("lowres, bad anatomy, deformed, extra limbs, extra fingers, "
                  "text, watermark, signature, jpeg artifacts, blurry, ugly")

# ── Traits visuels dérivés de l'empreinte holistique (tags → descripteurs) ──
# Petit dictionnaire CURÉ : on traduit le vocabulaire des traditions (éléments,
# tempéraments) en indices VISUELS (palette, lumière, matière). Volontairement
# étroit pour rester cohérent ; un tag inconnu est simplement ignoré.
_TRAITS = {
    "feu":      "warm fiery palette, ember glow, intense gaze",
    "eau":      "cool blue palette, flowing fabrics, serene reflections",
    "terre":    "earthy tones, grounded sturdy posture, natural textures",
    "air":      "airy pale palette, light fabrics, windswept hair",
    "solaire":  "radiant golden light, confident posture",
    "lunaire":  "soft silver moonlight, dreamy mysterious mood",
    "feminin":  "graceful features",
    "masculin": "strong features",
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


def prompt_portrait(fiche: dict, style: str = "") -> dict:
    """Fiche personnage → {prompt, negatif} pour un PORTRAIT.

    Champs lus (tous facultatifs sauf un identifiant) : nom, role, description,
    archetype, ambiance, empreinte (tags/éléments holistiques), style."""
    fiche = fiche or {}
    nom = _nettoyer(fiche.get("nom") or fiche.get("prenoms"))
    bouts = [f"portrait of {nom}" if nom else "character portrait"]
    if _nettoyer(fiche.get("role")):
        bouts.append(_nettoyer(fiche["role"]))
    if _nettoyer(fiche.get("archetype")):
        bouts.append(f"archetype: {_nettoyer(fiche['archetype'])}")
    if _nettoyer(fiche.get("description")):
        bouts.append(_nettoyer(fiche["description"]))
    bouts += _traits_de(fiche.get("empreinte") or fiche.get("tags"))
    if _nettoyer(fiche.get("ambiance")):
        bouts.append(_nettoyer(fiche["ambiance"]))
    bouts.append(_nettoyer(style) or _nettoyer(fiche.get("style")) or STYLE_DEFAUT)
    return {"prompt": ", ".join(b for b in bouts if b), "negatif": NEGATIF_DEFAUT}


def prompt_couverture(titre: str = "", synopsis: str = "", style: str = "",
                      personnages=None) -> dict:
    """Titre + synopsis (+ personnages) → {prompt, negatif} pour une COUVERTURE."""
    bouts = []
    if _nettoyer(titre):
        bouts.append(_nettoyer(titre))
    if _nettoyer(synopsis):
        bouts.append(_nettoyer(synopsis)[:300])
    noms = [_nettoyer(p.get("nom") if isinstance(p, dict) else p) for p in (personnages or [])]
    noms = [n for n in noms if n][:4]
    if noms:
        bouts.append("featuring " + ", ".join(noms))
    bouts.append(_nettoyer(style) or STYLE_COUVERTURE)
    return {"prompt": ", ".join(bouts), "negatif": NEGATIF_DEFAUT}
