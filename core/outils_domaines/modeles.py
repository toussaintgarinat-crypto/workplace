"""Outils du domaine « modèles » (S244b) : l'assistant voit les modèles et choisit le bon.

Câblés dans le Cœur (comme `sommeil`) : ils agissent sur la Gateway et la config, pas sur la
route d'une brique. Les règles de sécurité vivent dans `modeles_gateway` / `catalogue_modeles`
(catalogue serveur, test avant d'être gardé) — l'assistant ne fournit jamais d'URL ni de clé.
`modele_choisir` est réservé à l'admin du cerveau (`droits.RESERVES`) : changer le modèle de
tête change ce que paient et lisent tous les utilisateurs.
"""
import json

import catalogue_modeles
import config_assistant
import modeles_gateway

NOMS = ("modeles_disponibles", "modele_choisir")


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    if nom not in NOMS:
        return None
    args = args or {}
    try:
        if nom == "modeles_disponibles":
            return _j(await _disponibles((args.get("fournisseur") or "").strip()))
        return _j(await _choisir((args.get("fournisseur") or "").strip(),
                                 (args.get("modele") or "").strip(),
                                 (args.get("pour") or "assistant").strip()))
    except modeles_gateway.ValeurInvalide as e:
        return _j({"ok": False, "erreur": str(e)})
    except (modeles_gateway.Conflit, modeles_gateway.GatewayInjoignable) as e:
        return _j({"ok": False, "erreur": str(e)})


async def _disponibles(fournisseur: str) -> dict:
    conf = config_assistant.charger()
    if fournisseur:  # catalogue vivant d'un fournisseur (lu chez lui, cache 1 h)
        return await catalogue_modeles.lister(fournisseur)
    return {"tete_assistant": conf.get("model") or "(cascade auto)",
            "modeles_par_tache": conf.get("modeles_taches") or {},
            "taches": list(config_assistant.TACHES),
            "ajoutes": [m["nom"] for m in await modeles_gateway.lister()
                        if m["origine"] == "perso"],
            "fournisseurs": modeles_gateway.fournisseurs()}


async def _choisir(fournisseur: str, modele: str, pour: str) -> dict:
    if pour != "assistant" and pour not in config_assistant.TACHES:
        raise modeles_gateway.ValeurInvalide(
            f"« pour » = « assistant » ou une tâche parmi {', '.join(config_assistant.TACHES)}.")
    if not fournisseur and not modele and pour != "assistant":
        # Retire l'association d'une tâche (retour à la cascade).
        config_assistant.definir_modele_tache(pour, "")
        return {"ok": True, "pour": pour, "detail": "Association retirée : cascade habituelle."}
    # Déjà servi ? (`perso/…` complet passé dans `modele`) sinon on l'ajoute puis on le teste.
    if modele.startswith(modeles_gateway.PREFIXE_PERSO) and not fournisseur:
        nom = modele
        if not any(m["nom"] == nom for m in await modeles_gateway.lister()):
            raise modeles_gateway.ValeurInvalide(f"« {nom} » n'est pas servi : donne fournisseur + modèle.")
    else:
        nom = modeles_gateway.nom_perso(fournisseur, modele)
        deja = any(m["nom"] == nom for m in await modeles_gateway.lister())
        if not deja:
            r = await modeles_gateway.ajouter(fournisseur, modele)
            if not r["ok"]:
                return {"ok": False, "nom": nom,
                        "erreur": f"Le modèle ne répond pas, il n'a pas été gardé : {r['detail']}"}
    if pour == "assistant":
        config_assistant.definir_modele(nom, None)
    else:
        config_assistant.definir_modele_tache(pour, nom)
    return {"ok": True, "nom": nom, "pour": pour}
