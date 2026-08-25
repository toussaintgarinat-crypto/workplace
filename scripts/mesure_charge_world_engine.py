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
    {} si moins de 2 incréments observés (rien à mesurer)."""
    vus = sorted(observations, key=lambda o: o[0])
    if not vus:
        return {}

    increments = []
    i = 0
    while i < len(vus):
        current_tick = vus[i][1]
        # Find the last occurrence of this tick
        last_ts = vus[i][0]
        j = i + 1
        while j < len(vus) and vus[j][1] == current_tick:
            last_ts = vus[j][0]
            j += 1
        # Only add if it's a new tick
        if not increments or increments[-1][1] != current_tick:
            increments.append((last_ts, current_tick))
        i = j

    if len(increments) < 2:
        return {}
    ecarts = sorted(increments[i][0] - increments[i - 1][0] for i in range(1, len(increments)))
    return {
        "nb_ticks_observes": len(increments) - 1,
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
                f.write(json.dumps(ligne) + "\n")
            f.flush()
            time.sleep(args.intervalle_poll)
    print(f"observation terminée, écrit dans {chemin_obs}")


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
    print(f"peuplement : {ok} fondateurs créés, {ko} échecs "
          f"({len(mondes)} mondes × {args.fondateurs_par_monde})")

    Path(args.sortie).mkdir(parents=True, exist_ok=True)
    (Path(args.sortie) / "mondes.json").write_text(json.dumps(
        {"federation_id": federation["id"], "mondes": mondes}, indent=2))
    print(f"état écrit dans {args.sortie}/mondes.json")


def construire_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://192.168.1.89:6220")
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

    return p


def main() -> None:
    args = construire_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
