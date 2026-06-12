"""File d'entraînement des noms de marque (S43) — pilotée par l'**horloge S29**.

L'horloge appelle périodiquement `POST /entrainement/traiter` (tâche déclarée au
manifest, exactement comme les relances S22 ou le balayage des revues S33). Chaque
passe **fait avancer la file** d'un cran par commande :

    payee → en_entrainement → (entraîneur) → livree | echec

et **relance** les commandes restées impayées (compteur, comme un rappel J+x).

### Honnêteté sur l'entraînement (le point délicat)

Le POC S41 (`poc/DECISION.md`) a établi qu'entraîner un modèle openWakeWord par nom
demande un pipeline **Piper (TTS) + notebook openWakeWord sur GPU (~1 h)**. Cette
brique **n'embarque pas** ce pipeline. On refuse de **prétendre** entraîner un vrai
modèle là où il n'y en a pas. D'où un entraîneur **pluggable** :

  • si `ENTRAINEUR_CMD` est défini (un vrai job GPU branché en prod), on l'exécute ;
    le modèle produit est un VRAI modèle (`factice=False`).
  • sinon, **stand-in honnête** : on installe un modèle de substitution (copie d'un
    pré-entraîné) sous le nom de marque, **marqué `factice=True`**, pour prouver de
    bout en bout le câblage *livraison → nom sélectionnable sur le WS*. La commande
    porte le drapeau `factice` et un message explicite ; on ne fait croire à personne
    que la marque est réellement reconnue.

Le module ne dépend PAS d'openWakeWord (la source du stand-in est injectable) → la
file est testable hors ligne.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import commandes as cmd

logger = logging.getLogger(__name__)

MODELES_DIR = os.getenv("MODELES_DIR", "/data/modeles")
ENTRAINEUR_CMD = os.getenv("ENTRAINEUR_CMD")  # vrai job GPU branché en prod (optionnel)
# Au-delà de N passes de l'horloge sans paiement, on cesse de relancer (rappel poli, pas spam).
RELANCES_MAX = int(os.getenv("WAKEWORD_RELANCES_MAX", "3"))


def chemin_modele(slug: str, base: str | None = None) -> Path:
    return Path(base or MODELES_DIR) / f"{slug}.onnx"


def modele_livre(slug: str, base: str | None = None) -> bool:
    return chemin_modele(slug, base).exists()


def _source_standin() -> Path | None:
    """Modèle pré-entraîné servant de substitution honnête. Var `MODELE_SOURCE_STANDIN`
    sinon le `hey_jarvis` embarqué d'openWakeWord. None si introuvable (pas de mensonge)."""
    env = os.getenv("MODELE_SOURCE_STANDIN")
    if env and Path(env).exists():
        return Path(env)
    try:  # localisation paresseuse : ne charge pas openWakeWord si la var suffit
        import openwakeword
        p = Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
        return p if p.exists() else None
    except Exception:  # noqa: BLE001 - openwakeword absent (tests offline)
        return None


def entrainer(commande: dict, *, base_modeles: str | None = None,
              source_standin: Path | str | None = None) -> dict:
    """Produit le fichier ONNX pour `commande`. Renvoie {ok, factice, message}.

    Vrai entraîneur (`ENTRAINEUR_CMD`) si branché, sinon stand-in honnête marqué factice.
    Idempotent : si le modèle existe déjà, on ne ré-entraîne pas.
    """
    slug = commande["modele"]
    dest = chemin_modele(slug, base_modeles)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        return {"ok": True, "factice": bool(commande.get("factice")),
                "message": "Modèle déjà présent (idempotent)."}

    if ENTRAINEUR_CMD:
        # Vrai job : l'entraîneur reçoit le nom et le chemin de sortie par l'environnement.
        env = {**os.environ, "WAKEWORD_NOM": commande["nom_marque"],
               "WAKEWORD_SLUG": slug, "WAKEWORD_SORTIE": str(dest)}
        try:
            subprocess.run(ENTRAINEUR_CMD, shell=True, check=True, env=env, timeout=7200)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "factice": False,
                    "message": f"Entraîneur en échec : {e}"}
        if not dest.exists():
            return {"ok": False, "factice": False,
                    "message": "L'entraîneur n'a pas produit de modèle."}
        return {"ok": True, "factice": False,
                "message": "Modèle entraîné par l'entraîneur configuré."}

    # Stand-in honnête : copie d'un pré-entraîné sous le nom de marque, marqué factice.
    src = Path(source_standin) if source_standin else _source_standin()
    if not src or not Path(src).exists():
        return {"ok": False, "factice": False,
                "message": "Aucun entraîneur configuré et aucun modèle de substitution "
                           "disponible (ENTRAINEUR_CMD/MODELE_SOURCE_STANDIN absents)."}
    shutil.copyfile(src, dest)
    return {"ok": True, "factice": True,
            "message": "Modèle de SUBSTITUTION installé (stand-in). La marque n'est pas "
                       "réellement reconnue tant qu'un vrai entraîneur (ENTRAINEUR_CMD) "
                       "n'est pas branché. Câblage de livraison prouvé."}


def traiter_file(magasin: cmd.MagasinCommandes, *, base_modeles: str | None = None,
                 source_standin: Path | str | None = None) -> dict:
    """Une passe de la file (appelée par l'horloge). Avance chaque commande d'un cran
    et relance les impayées. Ne lève jamais : tout incident est tracé dans la commande."""
    magasin.init_db()
    rapport = {"avancees": [], "livrees": [], "echecs": [], "relancees": []}

    # 1) payée → en_entrainement (entrée en file)
    for c in magasin.lister("payee"):
        magasin.changer_etat(c["id"], "en_entrainement",
                             message="Entrée en file d'entraînement.")
        rapport["avancees"].append(c["id"])

    # 2) en_entrainement → livree | echec (exécution)
    for c in magasin.lister("en_entrainement"):
        res = entrainer(c, base_modeles=base_modeles, source_standin=source_standin)
        if res["ok"]:
            magasin.changer_etat(c["id"], "livree",
                                 message=res["message"], factice=res["factice"])
            rapport["livrees"].append(c["id"])
        else:
            magasin.changer_etat(c["id"], "echec", message=res["message"])
            rapport["echecs"].append(c["id"])
            logger.warning("Entraînement %s échoué : %s", c["id"], res["message"])

    # 3) relance des impayées (rappel borné, pas de spam)
    for c in magasin.lister("en_attente_paiement"):
        if (c.get("relances") or 0) < RELANCES_MAX:
            magasin.incr_relance(c["id"])
            rapport["relancees"].append(c["id"])

    rapport["resume"] = (f"{len(rapport['livrees'])} livrée(s), "
                         f"{len(rapport['avancees'])} en file, "
                         f"{len(rapport['echecs'])} échec(s), "
                         f"{len(rapport['relancees'])} relance(s).")
    return rapport
