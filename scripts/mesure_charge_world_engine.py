#!/usr/bin/env python3
"""Scénario de charge LIVE pour world-engine (préalable Sprint E) — voir
docs/superpowers/specs/2026-08-25-world-engine-mesure-charge-design.md.
Appels HTTP purs contre l'API publique : aucun code de la brique n'est importé."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 15


class ErreurAPI(Exception):
    """Réponse HTTP non-2xx de world-engine — message = corps de la réponse."""


def appeler(base_url: str, methode: str, chemin: str, cle_api: str,
            corps: dict | None = None) -> dict:
    """Appelle `methode chemin` sur world-engine avec le header X-API-Key. Lève
    ErreurAPI sur toute réponse non-2xx (le message inclut le corps renvoyé)."""
    data = json.dumps(corps).encode() if corps is not None else None
    req = urllib.request.Request(
        f"{base_url}{chemin}", data=data, method=methode,
        headers={"X-API-Key": cle_api, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            brut = resp.read()
            return json.loads(brut) if brut else {}
    except urllib.error.HTTPError as e:
        raise ErreurAPI(f"{methode} {chemin} -> {e.code} : "
                         f"{e.read().decode(errors='replace')}") from e


def creer_monde(base_url: str, cle_api: str, nb_cellules: int = 30) -> dict:
    return appeler(base_url, "POST", "/spatial/mondes", cle_api, {"nb_cellules": nb_cellules})


def creer_federation(base_url: str, cle_api: str, nom: str) -> dict:
    return appeler(base_url, "POST", "/federation", cle_api, {"nom": nom})


def rattacher_pays(base_url: str, cle_api: str, federation_id: str, monde_id: str) -> dict:
    return appeler(base_url, "POST", f"/federation/{federation_id}/rattacher", cle_api,
                    {"monde_id": monde_id})


def declarer_adjacence(base_url: str, cle_api: str, federation_id: str,
                        monde_id_a: str, monde_id_b: str) -> dict:
    return appeler(base_url, "POST", f"/federation/{federation_id}/adjacence", cle_api,
                    {"monde_id_a": monde_id_a, "monde_id_b": monde_id_b})


# Fiches parents FIXES et arbitraires, réutilisées pour chaque fondateur : seul
# l'enfant (le fondateur lui-même) doit varier pour ce scénario de charge, sa
# lignée n'a aucune importance narrative.
FICHE_PARENT_A = {"prenoms": "Fondateur", "nom": "A", "date_naissance": "1990-03-12",
                   "heure_naissance": "08:15", "latitude": 45.75, "longitude": 4.85,
                   "utc_offset": 1.0}
FICHE_PARENT_B = {"prenoms": "Fondateur", "nom": "B", "date_naissance": "1988-07-02",
                   "heure_naissance": "19:40", "latitude": 40.71, "longitude": -74.0,
                   "utc_offset": -5.0}


def creer_fondateur(base_url: str, cle_api: str, monde_id: str, sexe: str,
                     rng: random.Random) -> dict:
    corps = {
        "parent_a": FICHE_PARENT_A, "parent_b": FICHE_PARENT_B,
        "prenoms_enfant": "Fondateur", "nom_enfant": "",
        "latitude_enfant": rng.uniform(-60.0, 60.0),
        "longitude_enfant": rng.uniform(-170.0, 170.0),
        "heure_naissance_enfant": f"{rng.randrange(24):02d}:{rng.randrange(60):02d}",
        "utc_offset_enfant": float(rng.randrange(-11, 12)),
        "annee_enfant": 1990,
        "sexe_enfant": sexe,
        "monde_id": monde_id,
    }
    return appeler(base_url, "POST", "/genome/croiser", cle_api, corps)


def calculer_latences_tick(observations: list[tuple[float, int]]) -> dict:
    """`observations` = [(timestamp_epoch, tick_actuel), ...] pour UN monde, dans
    n'importe quel ordre. Ne retient que les instants où `tick_actuel` a
    RÉELLEMENT augmenté (déduplique le polling qui observe plusieurs fois le même
    tick) et calcule l'écart de temps entre deux incréments consécutifs. Renvoie
    {} si moins de 2 incréments observés (rien à mesurer).

    ⚠️ Correctif revue finale (Critical) : `ecart_min_s`/`ecart_p50_s`/
    `ecart_p95_s`/`ecart_max_s` sont quantifiés par la période de polling de
    l'appelant (`observer --intervalle-poll`) — chaque écart est un multiple
    entier de cette période, pas une mesure continue. Seul `ecart_moyen_s`
    (portée totale / nombre d'incréments, indépendant du pas de polling) est
    un estimateur non biaisé de l'intervalle réel entre deux ticks — c'est
    LUI qu'il faut lire pour juger une dérive, pas les percentiles."""
    vus = sorted(observations, key=lambda o: o[0])
    if not vus:
        return {}

    increments = []
    dernier_tick = None
    i = 0
    while i < len(vus):
        current_tick = vus[i][1]
        # Dernière occurrence de ce tick avant qu'il n'incrémente (borne
        # conservative de la fenêtre de transition, voir revue Task 3).
        last_ts = vus[i][0]
        j = i + 1
        while j < len(vus) and vus[j][1] == current_tick:
            last_ts = vus[j][0]
            j += 1
        # Garde de monotonicité (Minor revue finale) : un tick non croissant
        # (bruit/désordre) n'est jamais accepté comme un nouvel incrément.
        if dernier_tick is None or current_tick > dernier_tick:
            increments.append((last_ts, current_tick))
            dernier_tick = current_tick
        i = j

    if len(increments) < 2:
        return {}
    ecarts = sorted(increments[i][0] - increments[i - 1][0] for i in range(1, len(increments)))
    ecart_moyen = (increments[-1][0] - increments[0][0]) / (len(increments) - 1)
    return {
        "nb_ticks_observes": len(increments) - 1,
        "ecart_moyen_s": ecart_moyen,
        "ecart_min_s": ecarts[0],
        "ecart_p50_s": ecarts[len(ecarts) // 2],
        "ecart_p95_s": ecarts[min(len(ecarts) - 1, int(len(ecarts) * 0.95))],
        "ecart_max_s": ecarts[-1],
    }


def demarrer_horloge(base_url: str, cle_api: str, monde_id: str, intervalle_s: int) -> dict:
    return appeler(base_url, "POST", f"/horloge/{monde_id}/demarrer", cle_api,
                    {"intervalle_secondes": intervalle_s})


def arreter_horloge(base_url: str, cle_api: str, monde_id: str) -> dict:
    return appeler(base_url, "POST", f"/horloge/{monde_id}/arreter", cle_api)


def lire_horloge(base_url: str, cle_api: str, monde_id: str) -> dict:
    return appeler(base_url, "GET", f"/horloge/{monde_id}", cle_api)


def _charger_mondes(sortie: str) -> dict:
    return json.loads((Path(sortie) / "mondes.json").read_text())


def commande_demarrer_scheduler(args: argparse.Namespace) -> None:
    etat = _charger_mondes(args.sortie)
    for m in etat["mondes"]:
        demarrer_horloge(args.base_url, m["cle_api"], m["id"], args.intervalle_secondes)
        print(f"scheduler démarré pour {m['id']} (intervalle {args.intervalle_secondes}s)")


def commande_observer(args: argparse.Namespace) -> None:
    etat = _charger_mondes(args.sortie)
    mondes = etat["mondes"]
    fin = time.monotonic() + args.duree_minutes * 60
    chemin_obs = Path(args.sortie) / "observations.jsonl"
    with chemin_obs.open("a") as f:
        while time.monotonic() < fin:
            for m in mondes:
                try:
                    horloge = lire_horloge(args.base_url, m["cle_api"], m["id"])
                    ligne = {"ts": time.time(), "monde_id": m["id"],
                             "tick_actuel": horloge.get("tick_actuel"),
                             "actif": horloge.get("actif"), "erreur": None}
                except ErreurAPI as e:
                    ligne = {"ts": time.time(), "monde_id": m["id"],
                             "tick_actuel": None, "actif": None, "erreur": str(e)}
                except OSError as e:
                    # Correctif revue finale (Important) : un incident réseau isolé
                    # (reset, DNS, timeout) sur UNE lecture ne doit jamais faire
                    # planter une fenêtre d'observation de 12 minutes sans surveillance
                    # — même motif que le correctif OSError de `rafale-manuelle`.
                    ligne = {"ts": time.time(), "monde_id": m["id"], "tick_actuel": None,
                             "actif": None, "erreur": f"{type(e).__name__}: {e}"}
                f.write(json.dumps(ligne) + "\n")
            f.flush()
            time.sleep(args.intervalle_poll)
    print(f"observation terminée, écrit dans {chemin_obs}")


def tick_manuel(base_url: str, cle_api: str, monde_id: str) -> dict:
    return appeler(base_url, "POST", f"/horloge/{monde_id}/tick", cle_api)


def commande_arreter_scheduler(args: argparse.Namespace) -> None:
    etat = _charger_mondes(args.sortie)
    for m in etat["mondes"]:
        arreter_horloge(args.base_url, m["cle_api"], m["id"])
        print(f"scheduler arrêté pour {m['id']}")


def _tick_manuel_chronometre(base_url: str, cle_api: str, monde_id: str
                              ) -> tuple[dict | None, float, str | None]:
    """Chronomètre l'appel DANS le thread qui l'exécute, succès ou échec —
    renvoie (resultat, duree_s, erreur). Correctif revue finale (Critical) :
    mesurer au moment de la CONSOMMATION du future (`time.time() - debut_round`,
    ancienne version) donnait le temps CUMULÉ écoulé depuis le début du round
    jusqu'à cette consommation — un maximum croissant dans l'ordre de
    soumission, pas la durée de CET appel. Sur les données réelles de la
    mesure de charge, ça gonflait la médiane rapportée de ~1,0s (vraie
    médiane par tick) à ~5,8s. Chronométrer ICI, dans le thread, donne la
    vraie durée de chaque appel quel que soit l'ordre de consommation."""
    debut = time.time()
    try:
        resultat = tick_manuel(base_url, cle_api, monde_id)
        return resultat, time.time() - debut, None
    except ErreurAPI as e:
        return None, time.time() - debut, str(e)
    except OSError as e:
        # Un tick manuel peut légitimement dépasser TIMEOUT_S (15s) : une
        # naissance déclenche un appel HTTP vers `personnages` avec son propre
        # timeout de 30s (voir horloge_moteur.py). Un dépassement ici est un
        # résultat de mesure en soi (latence réelle sous charge), pas une
        # raison de faire planter toute la rafale — découvert en exécution
        # réelle (TimeoutError, sous-classe d'OSError, non catché à l'origine).
        return None, time.time() - debut, f"{type(e).__name__}: {e}"


def commande_rafale_manuelle(args: argparse.Namespace) -> None:
    """Déclenche des ticks manuels CONCURRENTS sur les 5 mondes, round par round —
    seul chemin qui expose `avertissements` (le scheduler les jette, voir
    Contexte technique du plan). Sollicite volontairement les verrous destination
    (Sprint D) en faisant tiquer plusieurs pays adjacents en même temps."""
    etat = _charger_mondes(args.sortie)
    mondes = etat["mondes"]
    chemin_avert = Path(args.sortie) / "avertissements.jsonl"
    with chemin_avert.open("a") as f:
        for round_ in range(args.nb_rounds):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(mondes)) as pool:
                futurs = {pool.submit(_tick_manuel_chronometre, args.base_url,
                                       m["cle_api"], m["id"]): m for m in mondes}
                for fut in concurrent.futures.as_completed(futurs):
                    m = futurs[fut]
                    resultat, duree, erreur = fut.result()
                    ligne = {"round": round_, "monde_id": m["id"], "duree_s": duree,
                              "tick_actuel": (resultat or {}).get("tick_actuel"),
                              "avertissements": (resultat or {}).get("avertissements", []),
                              "erreur": erreur}
                    f.write(json.dumps(ligne) + "\n")
            f.flush()
    print(f"{args.nb_rounds} rounds de tick manuel concurrent écrits dans {chemin_avert}")


def commande_setup(args: argparse.Namespace) -> None:
    rng = random.Random(args.graine)
    cles = [args.cle_api_a, args.cle_api_b]
    mondes = []
    for i in range(5):
        cle = cles[0] if i < 3 else cles[1]
        monde = creer_monde(args.base_url, cle, nb_cellules=30)
        mondes.append({"id": monde["id"], "cle_api": cle})
        print(f"monde {i + 1}/5 créé : {monde['id']} "
              f"(tenant {'A' if cle == cles[0] else 'B'})")

    federation = creer_federation(args.base_url, cles[0], "mesure-charge-sprint-e")
    for m in mondes:
        rattacher_pays(args.base_url, m["cle_api"], federation["id"], m["id"])
    for i in range(len(mondes)):
        j = (i + 1) % len(mondes)
        declarer_adjacence(args.base_url, mondes[i]["cle_api"], federation["id"],
                            mondes[i]["id"], mondes[j]["id"])
    print(f"fédération {federation['id']} : 5 pays en anneau (adjacence circulaire, "
          f"2 tenants mêlés)")

    taches = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrence) as pool:
        for m in mondes:
            for n in range(args.fondateurs_par_monde):
                sexe = "F" if n % 2 == 0 else "M"
                rng_tache = random.Random(rng.random())
                fut = pool.submit(creer_fondateur, args.base_url, m["cle_api"],
                                   m["id"], sexe, rng_tache)
                taches[fut] = m["id"]
        ok = ko = 0
        for fut in concurrent.futures.as_completed(taches):
            try:
                fut.result()
                ok += 1
            except ErreurAPI as e:
                ko += 1
                print(f"  fondateur échoué ({taches[fut]}) : {e}")
            except OSError as e:
                # Correctif revue finale (Important) : un incident réseau isolé sur
                # UN fondateur ne doit jamais faire échouer tout le peuplement
                # (~200 appels) — même motif que `rafale-manuelle`/`observer`.
                ko += 1
                print(f"  fondateur échoué ({taches[fut]}) : {type(e).__name__}: {e}")
    print(f"peuplement : {ok} fondateurs créés, {ko} échecs "
          f"({len(mondes)} mondes × {args.fondateurs_par_monde})")

    Path(args.sortie).mkdir(parents=True, exist_ok=True)
    chemin_mondes = Path(args.sortie) / "mondes.json"
    chemin_mondes.write_text(json.dumps(
        {"federation_id": federation["id"], "mondes": mondes}, indent=2))
    # Correctif revue finale (Important) : ce fichier contient les cle_api EN
    # CLAIR (nécessaire aux sous-commandes suivantes) — 0600 plutôt que le 0644
    # par défaut, jamais lisible par d'autres utilisateurs de la machine.
    chemin_mondes.chmod(0o600)
    print(f"état écrit dans {chemin_mondes} (permissions 0600)")


def construire_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://192.168.1.89:6230")
    p.add_argument("--sortie", default="/tmp/world-engine-charge")
    sous = p.add_subparsers(dest="commande", required=True)

    s = sous.add_parser("setup", help="crée 5 mondes fédérés + peuple de fondateurs")
    s.add_argument("--cle-api-a", required=True)
    s.add_argument("--cle-api-b", required=True)
    s.add_argument("--fondateurs-par-monde", type=int, default=40)
    s.add_argument("--concurrence", type=int, default=5)
    s.add_argument("--graine", type=int, default=42)
    s.set_defaults(func=commande_setup)

    s = sous.add_parser("demarrer-scheduler", help="active le scheduler auto sur les 5 mondes")
    s.add_argument("--intervalle-secondes", type=int, default=5)
    s.set_defaults(func=commande_demarrer_scheduler)

    s = sous.add_parser("observer", help="échantillonne tick_actuel de chaque monde")
    s.add_argument("--duree-minutes", type=float, default=12.0)
    s.add_argument("--intervalle-poll", type=float, default=2.0)
    s.set_defaults(func=commande_observer)

    s = sous.add_parser("arreter-scheduler", help="désactive le scheduler auto sur les 5 mondes")
    s.set_defaults(func=commande_arreter_scheduler)

    s = sous.add_parser("rafale-manuelle", help="ticks manuels concurrents, capture les avertissements")
    s.add_argument("--nb-rounds", type=int, default=20)
    s.set_defaults(func=commande_rafale_manuelle)

    return p


def main() -> None:
    args = construire_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
