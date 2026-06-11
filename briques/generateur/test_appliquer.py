"""Preuve offline de « appliquer l'incrément » (S32) — fonction pure, aucun réseau.

On vérifie `appliquer.construire_plan_enrichi` :

  1. **ajout** : les modules proposés deviennent de vraies entités CRUD (id slugifié,
     champs par défaut, description = raison, origine=increment), plan enrichi ;
  2. **idempotence** : un module dont l'id existe déjà n'est PAS dupliqué ;
  3. **honnêteté** : proposition sans module (repli heuristique) → aucun ajout, plan
     inchangé ;
  4. **robustesse** : entrées dégénérées (nom vide, module non-dict, plan vide) tolérées
     sans exception ;
  5. **gabarit** : le plan enrichi se régénère réellement en HTML (le nouveau module
     apparaît dans l'app) — branche le module sur le vrai moteur de rendu.

Lancer : `python3 test_appliquer.py`.
"""
import appliquer


PLAN = {"nom_app": "Cabinet", "entites": [
    {"id": "planning", "nom": "Planning"},
    {"id": "devis", "nom": "Devis"},
]}


def run():
    ok = 0

    # 1) Ajout : 1 module proposé → 1 entité fonctionnelle.
    prop = {"modules_proposes": [
        {"nom": "Gestion des absences", "raison": "planning saturé"},
    ]}
    plan2, ajoutes = appliquer.construire_plan_enrichi(PLAN, prop)
    assert ajoutes == [{"id": "gestion-des-absences", "nom": "Gestion des absences"}], ajoutes
    nouvelle = next(e for e in plan2["entites"] if e["id"] == "gestion-des-absences")
    assert nouvelle["description"] == "planning saturé", nouvelle
    assert nouvelle["origine"] == "increment", nouvelle
    assert {c["cle"] for c in nouvelle["champs"]} == {"libelle", "statut", "date", "montant", "notes"}, nouvelle["champs"]
    assert len(plan2["entites"]) == 3 and PLAN["entites"] != plan2["entites"], "plan d'origine non muté en place"
    print("✅ 1. ajout : module proposé → entité CRUD (champs défaut, origine=increment), plan enrichi")
    ok += 1

    # 2) Idempotence : un module déjà présent (par slug du nom) n'est pas dupliqué.
    prop_dup = {"modules_proposes": [
        {"nom": "Planning", "raison": "déjà là"},          # id 'planning' existe
        {"nom": "Gestion des absences", "raison": "neuf"},  # nouveau
    ]}
    plan3, ajoutes3 = appliquer.construire_plan_enrichi(PLAN, prop_dup)
    assert [a["id"] for a in ajoutes3] == ["gestion-des-absences"], ajoutes3
    assert sum(1 for e in plan3["entites"] if e["id"] == "planning") == 1, "pas de doublon planning"
    print("✅ 2. idempotence : module déjà présent ignoré, pas de doublon")
    ok += 1

    # 3) Honnêteté : repli heuristique (aucun module proposé) → aucun ajout.
    plan4, ajoutes4 = appliquer.construire_plan_enrichi(PLAN, {"modules_proposes": [], "source": "heuristique"})
    assert ajoutes4 == [], ajoutes4
    assert len(plan4["entites"]) == 2, "plan inchangé sans proposition"
    print("✅ 3. honnêteté : proposition sans module → aucun ajout, plan inchangé")
    ok += 1

    # 4) Robustesse : entrées dégénérées tolérées.
    sale = {"modules_proposes": [{"nom": "  "}, "pas un dict", {"raison": "sans nom"}, {"nom": "Suivi RGPD"}]}
    plan5, ajoutes5 = appliquer.construire_plan_enrichi({}, sale)
    assert [a["id"] for a in ajoutes5] == ["suivi-rgpd"], ajoutes5
    assert appliquer.construire_plan_enrichi(None, None) == ({"entites": []}, []), "plan/proposition None tolérés"
    print("✅ 4. robustesse : nom vide / non-dict / plan vide tolérés, aucune exception")
    ok += 1

    # 5) Gabarit : le plan enrichi se régénère réellement en HTML.
    from gabarit import generer_html
    plan6, _ = appliquer.construire_plan_enrichi(PLAN, prop)
    html = generer_html({"nom_entreprise": "Cabinet"}, plan6)
    assert "Gestion des absences" in html, "le module ajouté doit apparaître dans l'app régénérée"
    print("✅ 5. gabarit : plan enrichi régénéré, le nouveau module apparaît dans l'app")
    ok += 1

    print(f"\n{ok}/5 scénarios OK")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() == 5 else 1)
