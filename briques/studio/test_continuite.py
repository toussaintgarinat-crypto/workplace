"""Tests — Journal de continuité du Studio, repris hors Oria (S51).

Trois dérives d'une série au long cours, corrigées au niveau de la génération :
  • PRÉNOMS instables → on rappelle au Scénariste les noms canoniques établis ;
  • REBOOT de l'histoire → on lui rappelle les faits IRRÉVERSIBLES déjà acquis ;
  • ANGLAIS résiduel  → garde-langue du Script Doctor + détecteur honnête.

Fonctions pures + récolte canon avec Gateway mockée."""
import asyncio

import studio as A


# ── Normalisation : le canon existe toujours (rétrocompat) ───────
def test_normaliser_cree_le_canon_vide():
    s = A._normaliser({"titre": "T", "episodes": []})
    assert s["canon"] == {"personnages": [], "acquis": [], "apparitions": {}}


def test_normaliser_preserve_un_canon_existant():
    s = A._normaliser({"titre": "T", "canon": {"personnages": ["ELARA"], "acquis": ["x"]}})
    assert s["canon"]["personnages"] == ["ELARA"]
    assert s["canon"]["acquis"] == ["x"]


# ── Personnages connus : fiches + récoltés, dédoublonnés ─────────
def test_personnages_connus_fusionne_fiches_et_canon():
    serie = {
        "personnages": [{"nom": "Elara"}, {"nom": "Kenji"}],
        "canon": {"personnages": ["ELARA", "Zara"]},
    }
    noms = A._personnages_connus(serie)
    assert [n.upper() for n in noms] == ["ELARA", "KENJI", "ZARA"]


def test_personnages_connus_ignore_narrateur():
    serie = {"personnages": [], "canon": {"personnages": ["NARRATEUR", "Maya"]}}
    assert A._personnages_connus(serie) == ["Maya"]


def test_consigne_personnages_vide_si_aucun():
    assert A._consigne_personnages({"personnages": [], "canon": {"personnages": []}}) == ""


def test_consigne_personnages_liste_les_noms():
    txt = A._consigne_personnages({"canon": {"personnages": ["ELARA", "KENJI"]}})
    assert "ELARA" in txt and "KENJI" in txt
    assert "EXACTEMENT" in txt


# ── Faits acquis : anti-reboot ───────────────────────────────────
def test_consigne_acquis_vide_si_aucun():
    assert A._consigne_acquis({"canon": {"acquis": []}}) == ""


def test_consigne_acquis_liste_les_faits():
    txt = A._consigne_acquis({"canon": {"acquis": ["L'Arbre-Monde est planté à Paris."]}})
    assert "Arbre-Monde" in txt
    assert "rejoue" in txt.lower()


# ── Fusion canon : idempotente, dédoublonnée, plafonnée ──────────
def test_fusion_canon_ajoute_et_dedoublonne():
    serie = {"canon": {"personnages": ["ELARA"], "acquis": ["fait A"]}}
    A._fusion_canon(serie, ["elara", "Kenji"], ["fait A", "fait B"])
    assert [n.upper() for n in serie["canon"]["personnages"]] == ["ELARA", "KENJI"]
    assert serie["canon"]["acquis"] == ["fait A", "fait B"]


def test_fusion_canon_ignore_narrateur():
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, ["NARRATEUR", "Liam"], [])
    assert [n.upper() for n in serie["canon"]["personnages"]] == ["LIAM"]


def test_fusion_canon_plafonne_les_acquis():
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, [], [f"fait {i}" for i in range(A.CANON_MAX_ACQUIS + 10)])
    assert len(serie["canon"]["acquis"]) == A.CANON_MAX_ACQUIS
    assert serie["canon"]["acquis"][-1] == f"fait {A.CANON_MAX_ACQUIS + 9}"


def test_fusion_canon_compte_les_apparitions():
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, ["Elara"], [])
    A._fusion_canon(serie, ["elara", "Kaël"], [])
    A._fusion_canon(serie, ["ELARA"], [])
    assert serie["canon"]["apparitions"] == {"ELARA": 3, "KAËL": 1}


def test_fusion_canon_compte_une_seule_fois_par_chapitre():
    """Une même personne mentionnée plusieurs fois DANS UN MÊME chapitre ne doit
    compter que pour UNE apparition — sinon le seuil de récurrence du pont
    world-engine (3 CHAPITRES distincts) serait faussé par le style d'écriture."""
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, ["Elara", "Elara", "elara"], [])
    assert serie["canon"]["apparitions"] == {"ELARA": 1}


def test_fusion_canon_apparitions_ignore_narrateur():
    serie = {"canon": {"personnages": [], "acquis": []}}
    A._fusion_canon(serie, ["NARRATEUR"], [])
    assert serie["canon"]["apparitions"] == {}


# ── Récolte canon : Gateway mockée + repli honnête ───────────────
def test_recolter_canon_alimente_depuis_le_script(monkeypatch):
    async def faux_gw(*a, **k):
        return '{"personnages": ["ELARA", "KAEL"], "acquis": ["Paris est sauvée."]}'
    monkeypatch.setattr(A, "_gateway_answer", faux_gw)
    serie = {"canon": {"personnages": [], "acquis": []}}
    asyncio.run(A._recolter_canon(serie, "ELARA: Bonjour. KAEL: On a réussi."))
    assert [n.upper() for n in serie["canon"]["personnages"]] == ["ELARA", "KAEL"]
    assert serie["canon"]["acquis"] == ["Paris est sauvée."]


def test_recolter_canon_repli_honnete_si_gateway_ko(monkeypatch):
    async def gw_ko(*a, **k):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(A, "_gateway_answer", gw_ko)
    serie = {"canon": {"personnages": ["ELARA"], "acquis": []}}
    asyncio.run(A._recolter_canon(serie, "un script"))
    assert serie["canon"]["personnages"] == ["ELARA"]


def test_recolter_canon_script_vide_noop(monkeypatch):
    appels = {"n": 0}

    async def compteur(*a, **k):
        appels["n"] += 1
        return "{}"
    monkeypatch.setattr(A, "_gateway_answer", compteur)
    serie = {"canon": {"personnages": [], "acquis": []}}
    asyncio.run(A._recolter_canon(serie, "   "))
    assert appels["n"] == 0


# ── Injection dans le prompt du Scénariste ───────────────────────
def test_tache_scenariste_injecte_personnages_et_acquis():
    serie = {
        "titre": "T", "bible": {}, "episodes": [],
        "canon": {"personnages": ["ELARA"], "acquis": ["L'Arbre-Monde est planté."]},
    }
    tache = A._tache_scenariste(serie, 5, "suite", "")
    assert "ELARA" in tache
    assert "Arbre-Monde" in tache


def test_tache_scenariste_sans_canon_reste_propre():
    serie = {"titre": "T", "bible": {}, "episodes": []}
    tache = A._tache_scenariste(serie, 1, "ouverture", "")
    assert "PERSONNAGES DÉJÀ ÉTABLIS" not in tache
    assert "FAITS DÉJÀ ACQUIS" not in tache


# ── Garde-langue : Script Doctor impose la langue ────────────────
def test_tache_doctor_impose_la_langue_de_travail():
    fr = A._tache_doctor({"langue": "fr"}, "un script")
    assert "français" in fr.lower()
    assert "anglicisme" in fr.lower()
    es = A._tache_doctor({"langue": "es"}, "un script")
    assert "espagnol" in es.lower()


# ── Détecteur d'anglicismes : honnête et étroit ──────────────────
def test_anglicismes_repere_le_jargon():
    txt = "Le boss final arrive, something is wrong avec le tutoriel."
    trouves = A._anglicismes(txt, {"langue": "fr"})
    assert "boss" in trouves and "something" in trouves and "wrong" in trouves


def test_anglicismes_dedoublonne():
    assert A._anglicismes("boss boss BOSS", {"langue": "fr"}) == ["boss"]


def test_anglicismes_aucun_faux_positif_sur_du_francais():
    assert A._anglicismes("Elara avance dans la forêt magique et plante la graine.",
                          {"langue": "fr"}) == []


def test_anglicismes_muet_si_langue_de_travail_anglaise():
    assert A._anglicismes("the boss is loading the game over screen",
                          {"langue": "en"}) == []


def test_anglicismes_repere_les_contractions():
    trouves = A._anglicismes("Elara dit : don't worry, we'll be fine, let's go.",
                             {"langue": "fr"})
    assert "don't" in trouves and "we'll" in trouves and "let's go" in trouves


def test_anglicismes_repere_les_expressions():
    trouves = A._anglicismes("Soudain, game over. Oh my god, what the... no way.",
                             {"langue": "fr"})
    assert "game over" in trouves and "oh my god" in trouves and "no way" in trouves


def test_anglicismes_repere_le_jargon_etoffe():
    trouves = A._anglicismes("Il faut un checkpoint avant le boss, sinon respawn et game over.",
                             {"langue": "fr"})
    assert {"checkpoint", "boss", "respawn"} <= set(trouves)


def test_anglicismes_epargne_les_homographes_francais():
    phrase = ("La note finale est importante : le plan du grand car principal occupe une "
              "table de la salle, à part la main du héros.")
    assert A._anglicismes(phrase, {"langue": "fr"}) == []


def test_anglicismes_ordre_d_apparition():
    trouves = A._anglicismes("boss game over boss", {"langue": "fr"})
    assert trouves == ["game over", "boss"]


# ── Suivi des tomes : statut + bilan structurel ──────────────────
def test_normaliser_pose_le_statut_des_tomes():
    s = A._normaliser({"titre": "T", "episodes": []})
    assert all(t.get("statut") == "en_cours" for t in A._tous_tomes(s))


def test_chapitres_du_tome_filtre_et_ordonne():
    serie = {"episodes": [{"n": 3, "tome_id": "t1"}, {"n": 1, "tome_id": "t1"},
                          {"n": 2, "tome_id": "t2"}]}
    ns = [c["n"] for c in A._chapitres_du_tome(serie, "t1")]
    assert ns == [1, 3]


def test_bilan_structurel_sans_arc_ni_chapitre():
    serie = {"episodes": []}
    tome = {"id": "t1", "resume": "", "statut": "en_cours"}
    b = A._bilan_structurel(serie, tome)
    assert b == {"nb_chapitres": 0, "a_un_arc": False,
                 "statut": "en_cours", "finit_sur_cliffhanger": False}


def test_bilan_structurel_detecte_la_fin_sur_cliffhanger():
    serie = {"episodes": [{"n": 1, "tome_id": "t1"},
                          {"n": 2, "tome_id": "t1", "fin_episode": True}]}
    tome = {"id": "t1", "resume": "sauver la ville", "statut": "en_cours"}
    b = A._bilan_structurel(serie, tome)
    assert b["nb_chapitres"] == 2
    assert b["a_un_arc"] is True
    assert b["finit_sur_cliffhanger"] is True
