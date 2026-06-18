"""Moteur OCR PROVIDER-AGNOSTIQUE — orchestrateur (« les yeux »).

On balaie les fournisseurs DISPONIBLES (cf. fournisseurs.py) dans l'ordre de préférence et
on retient le PREMIER texte non vide obtenu. La brique rapatrie toujours le texte et le
sert depuis sa propre réponse : l'appelant n'a jamais à joindre Mistral/Google ni à
connaître les clés.

Repli HONNÊTE : si AUCUN moteur n'est configuré, ou si tous échouent (lib absente / clé
invalide / format non géré / timeout), on rend un message qui le DIT (`place_holder: true`)
avec le détail des erreurs. On ne casse jamais l'appelant, et on ne fait JAMAIS passer un
repli pour du vrai texte extrait.
"""
from typing import Optional

import fournisseurs


async def fournisseur_actif() -> Optional[str]:
    """Premier fournisseur réellement utilisable (pour /sante).

    Pour les moteurs locaux comme pour les hébergés, la présence de la lib / clé suffit :
    on ne brûle pas un OCR juste pour un état de santé."""
    dispo = fournisseurs.disponibles()
    return dispo[0] if dispo else None


async def extraire(data: bytes, nom_fichier: str = "", mime: str = "",
                   fournisseur: Optional[str] = None) -> dict:
    """Rend {texte, backend, place_holder, nb_caracteres, ...}.

    `fournisseur` (optionnel) force un moteur précis ; sinon on suit l'ordre de préférence.
    """
    if not data:
        return {"texte": "", "backend": "placeholder", "place_holder": True,
                "nb_caracteres": 0, "note": "Aucun contenu reçu à lire."}

    if fournisseur:                                   # forçage explicite d'un moteur
        f = fournisseurs.REGISTRE.get(fournisseur.lower())
        candidats = [fournisseur.lower()] if (f and f.disponible()) else []
    else:
        candidats = fournisseurs.disponibles()

    if not candidats:
        note = (f"Moteur OCR « {fournisseur} » indisponible (lib/clé absente)." if fournisseur
                else "Aucun moteur OCR configuré : installez MarkItDown/Tesseract en local, "
                     "ou renseignez MISTRAL_API_KEY / GOOGLE_VISION_API_KEY.")
        return {"texte": "", "backend": "placeholder", "place_holder": True,
                "nb_caracteres": 0, "note": note, "fournisseurs": candidats}

    erreurs = {}
    for nom in candidats:
        try:
            texte = await fournisseurs.REGISTRE[nom].extraire(data, nom_fichier, mime)
            if texte and texte.strip():
                texte = texte.strip()
                return {"texte": texte, "backend": nom, "place_holder": False,
                        "nb_caracteres": len(texte)}
            erreurs[nom] = "aucun texte extrait (document vide ou illisible)"
        except Exception as e:  # noqa: BLE001
            erreurs[nom] = str(e)[:160]

    return {"texte": "", "backend": "placeholder", "place_holder": True, "nb_caracteres": 0,
            "note": "Moteurs OCR essayés sans succès : " + ", ".join(candidats),
            "erreurs": erreurs}
