"""Tests du dictionnaire de significations (S49) — surtout la COMPLÉTUDE : toute valeur
que le moteur peut calculer doit avoir une lecture (sinon le portrait afficherait du vide)."""
import significations as Z
import traditions as T


def test_tous_les_signes_ont_un_sens():
    for nom, _ in T.SIGNES:
        assert Z.SIGNES_SENS.get(nom), f"signe sans sens : {nom}"


def test_tous_les_animaux_chinois():
    for nom, _ in T.ANIMAUX_CHINOIS:
        assert Z.CHINOIS_SENS.get(nom), f"animal sans sens : {nom}"


def test_toutes_divinites_egyptiennes():
    for *_, nom in T._SEGMENTS_EGYPTE:
        assert Z.EGYPTE_SENS.get(nom), f"divinité sans sens : {nom}"


def test_tous_les_arbres_celtes():
    for *_, nom in T._SEGMENTS_CELTE:
        assert Z.CELTE_SENS.get(nom), f"arbre sans sens : {nom}"


def test_tous_les_totems():
    for *_, nom in T._SEGMENTS_TOTEM:
        assert Z.TOTEM_SENS.get(nom), f"totem sans sens : {nom}"


def test_tous_les_glyphes_maya():
    for g in T.GLYPHES_MAYA:
        assert Z.MAYA_SENS.get(g), f"glyphe sans sens : {g}"


def test_tous_les_nakshatras():
    for n in T.NAKSHATRAS:
        assert Z.NAKSHATRA_SENS.get(n), f"nakshatra sans sens : {n}"


def test_tous_les_nombres():
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 22, 33):
        assert Z.NOMBRE_SENS.get(n), f"nombre sans sens : {n}"


def test_expliquer_empreinte_complete():
    """Sur une fiche complète, chaque entrée a une clé, une valeur ET un sens non vides."""
    trad = T.calculer({
        "prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
        "heure_naissance": "14:30", "latitude": 43.6, "longitude": 1.44, "utc_offset": 2.0})
    emp = Z.expliquer(trad)
    cles = {e["cle"] for e in emp}
    assert {"Soleil", "Lune", "Ascendant", "Égypte", "Celte", "Maya (Tzolkin)",
            "Chemin de vie", "Nakshatra"} <= cles
    for e in emp:
        assert e["valeur"] and e["sens"], f"entrée incomplète : {e}"


def test_expliquer_date_seule_omet_les_sections_manquantes():
    emp = Z.expliquer(T.calculer({"date_naissance": "1990-09-05"}))
    cles = {e["cle"] for e in emp}
    assert "Soleil" in cles
    assert "Lune" not in cles and "Ascendant" not in cles   # pas d'heure → omis


# ── i18n anglais (S194) ────────────────────────────────────────────
def _fiche_complete():
    return T.calculer({
        "prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
        "heure_naissance": "14:30", "latitude": 43.6, "longitude": 1.44, "utc_offset": 2.0})


def test_expliquer_langue_fr_defaut_inchange():
    """Garde-fou de non-régression : `langue` omise ou "fr" = comportement identique."""
    trad = _fiche_complete()
    assert Z.expliquer(trad) == Z.expliquer(trad, "fr")


def test_expliquer_langue_en_memes_cles_valeurs_traduites():
    trad = _fiche_complete()
    emp = Z.expliquer(trad, "en")
    cles = {e["cle"] for e in emp}
    assert {"Sun", "Moon", "Ascendant", "Egyptian", "Celtic", "Maya (Tzolkin)",
            "Life Path", "Nakshatra"} <= cles
    for e in emp:
        assert e["valeur"] and e["sens"], f"entrée EN incomplète : {e}"
    soleil = next(e for e in emp if e["cle"] == "Sun")
    assert "Aries" in soleil["valeur"] or "Scorpio" in soleil["valeur"] or soleil["valeur"]
    maya = next(e for e in emp if e["cle"] == "Maya (Tzolkin)")
    assert any(g in maya["valeur"] for g in T.GLYPHES_MAYA)   # noms Maya inchangés en anglais


def test_toutes_les_tables_en_completes():
    """Même garde-fou de complétude que les tables FR, côté anglais."""
    for nom, _ in T.SIGNES:
        assert Z.SIGNES_SENS_EN.get(nom), f"signe sans sens EN : {nom}"
    for nom, _ in T.ANIMAUX_CHINOIS:
        assert Z.CHINOIS_SENS_EN.get(nom), f"animal sans sens EN : {nom}"
    for *_, nom in T._SEGMENTS_EGYPTE:
        assert Z.EGYPTE_SENS_EN.get(nom), f"divinité sans sens EN : {nom}"
    for *_, nom in T._SEGMENTS_CELTE:
        assert Z.CELTE_SENS_EN.get(nom), f"arbre sans sens EN : {nom}"
    for *_, nom in T._SEGMENTS_TOTEM:
        assert Z.TOTEM_SENS_EN.get(nom), f"totem sans sens EN : {nom}"
    for g in T.GLYPHES_MAYA:
        assert Z.MAYA_SENS_EN.get(g), f"glyphe sans sens EN : {g}"
    for n in T.NAKSHATRAS:
        assert Z.NAKSHATRA_SENS_EN.get(n), f"nakshatra sans sens EN : {n}"
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 22, 33):
        assert Z.NOMBRE_SENS_EN.get(n), f"nombre sans sens EN : {n}"


# ── Glossaire (bulles + légende PDF) ───────────────────────────────
def test_glossaire_fr_structure():
    g = Z.glossaire("fr")
    assert [t["theme"] for t in g] == [
        "Astrologie occidentale", "Astrologie chinoise", "Astrologie védique",
        "Autres traditions", "Numérologie",
        "Statistiques de personnalité", "Synthèse du portrait",
        "Carte astro complète",
    ]
    ids = {it["id"] for t in g for it in t["items"]}
    assert {"soleil", "lune", "ascendant", "chinoise", "animal_heure",
            "vedique", "nakshatra", "egypte", "celte", "totem", "maya",
            "chemin_de_vie", "expression", "archetype", "forces",
            "faiblesse", "pierre"} <= ids
    assert {"stat_charisme", "stat_combativite", "stat_sagesse",
            "stat_creativite", "stat_discretion", "stat_stabilite",
            "stat_emotivite", "stat_energie"} <= ids
    for t in g:
        for it in t["items"]:
            assert it["label"] and it["definition"], f"entrée glossaire incomplète : {it}"


def test_glossaire_en_memes_ids_memes_themes():
    """Mêmes ids, mêmes thèmes (en anglais), que en français."""
    fr = Z.glossaire("fr")
    en = Z.glossaire("en")
    fr_ids = {it["id"] for t in fr for it in t["items"]}
    en_ids = {it["id"] for t in en for it in t["items"]}
    assert fr_ids == en_ids
    assert [t["theme"] for t in en] != [t["theme"] for t in fr]  # thèmes traduits
    for t in en:
        for it in t["items"]:
            assert it["label"] and it["definition"], f"entrée EN incomplète : {it}"


def test_glossaire_completude_ids_dans_tables():
    """Chaque id du glossaire existe dans GLOSSAIRE_FR et GLOSSAIRE_EN."""
    ids_TH = set(Z._GLOSSAIRE_THEMES_IDS)  # union des ids par thème
    for i in ids_TH:
        assert Z.GLOSSAIRE_FR.get(i), f"id sans définition FR : {i}"
        assert Z.GLOSSAIRE_EN.get(i), f"id sans définition EN : {i}"


def test_expliquer_empreinte_possede_ids_stables():
    """Chaque entrée de l'empreinte porte un `id` stable connu du glossaire."""
    trad = _fiche_complete()
    emp = Z.expliquer(trad, "fr")
    ids_connus = {it["id"] for t in Z.glossaire("fr") for it in t["items"]}
    for e in emp:
        assert e.get("id") and e["id"] in ids_connus, f"entrée sans id stable : {e}"
    cles_vers_ids = {e["cle"]: e["id"] for e in emp}
    assert cles_vers_ids["Soleil"] == "soleil"
    assert cles_vers_ids["Lune"] == "lune"
    assert cles_vers_ids["Ascendant"] == "ascendant"


# ── Clefs theme_complet (task 10) ─────────────────────────────────
def test_clefs_corps_10_entrees():
    assert set(Z.CLEFS_CORPS.keys()) == {"Soleil", "Lune", "Mercure", "Vénus",
                                         "Mars", "Jupiter", "Saturne", "Uranus",
                                         "Neptune", "Pluton"}
    for corps, clef in Z.CLEFS_CORPS.items():
        assert "fr" in clef and "en" in clef


def test_clefs_points_evolutifs_4():
    assert set(Z.CLEFS_POINTS_EVOLUTIFS.keys()) == {"noeud_nord", "noeud_sud",
                                                     "chiron", "lilith"}


def test_clefs_aspects_presentes():
    assert "trigone" in Z.CLEFS_ASPECTS
    assert "carre" in Z.CLEFS_ASPECTS


def test_clefs_dominantes_element():
    assert "Feu" in Z.CLEFS_DOMINANTES.get("element", {})


def test_expliquer_avec_theme_complet():
    """expliquer() avec theme_complet ajoute une sous-section carte astro."""
    trad = {"signe_solaire": {"nom": "Bélier"}}
    tc = {"fondations": {"soleil": {"signe": "Bélier", "longitude": 0.0}},
          "dix_corps": {"Soleil": {"signe": "Bélier"}},
          "dominantes": {"element": {"dominant": "Feu"}}}
    res = Z.expliquer(trad, "fr", theme_complet=tc)
    assert any("carte" in e.get("id", "").lower() or "theme" in e.get("id", "").lower()
               for e in res)


def test_expliquer_sans_theme_complet_compatible():
    """expliquer() sans theme_complet reste compatible (pas d'erreur)."""
    trad = {"signe_solaire": {"nom": "Bélier"}}
    res = Z.expliquer(trad, "fr")
    assert isinstance(res, list)


# ── Couche didactique (cartes pédagogiques) ───────────────────────
_DIDACTIQUE_IDS_ATTENDUS = [
    "theme_fondation_soleil", "theme_fondation_lune",
    "theme_fondation_ascendant", "theme_fondation_descendant",
    "theme_fondation_milieu_du_ciel", "theme_fondation_fond_du_ciel",
    "theme_corps_soleil", "theme_corps_lune", "theme_corps_mercure",
    "theme_corps_vénus", "theme_corps_mars", "theme_corps_jupiter",
    "theme_corps_saturne", "theme_corps_uranus", "theme_corps_neptune",
    "theme_corps_pluton",
    "theme_point_noeud_nord", "theme_point_noeud_sud",
    "theme_point_chiron", "theme_point_lilith",
    "theme_fondations", "theme_corps", "theme_points_evolutifs",
    "theme_maisons", "theme_aspects", "theme_dominantes",
]


def test_didactique_fr_structure():
    d = Z.didactique("fr")
    assert set(d.keys()) == set(_DIDACTIQUE_IDS_ATTENDUS), (
        f"manquent={set(_DIDACTIQUE_IDS_ATTENDUS)-set(d.keys())}, "
        f"en_trop={set(d.keys())-set(_DIDACTIQUE_IDS_ATTENDUS)}")
    for k, e in d.items():
        assert e.get("question"), f"{k} sans question"
        assert isinstance(e.get("domaines"), list) and len(e["domaines"]) >= 3, (
            f"{k} domaines invalides")
        assert e.get("conclusion"), f"{k} sans conclusion"


def test_didactique_ids_connus_du_glossaire():
    """Toute clé didactique existe dans GLOSSAIRE_FR (garde-fou doublon)."""
    for k in Z.DIDACTIQUE_FR:
        assert Z.GLOSSAIRE_FR.get(k), f"clé didactique inconnue du glossaire FR : {k}"


def test_didactique_distinction_soleil_lune_facettes():
    """Soleil/Lune ont 2 facettes distinctes (pilier vs corps)."""
    d = Z.didactique("fr")
    assert d["theme_fondation_soleil"]["conclusion"] != d["theme_corps_soleil"]["conclusion"]
    assert d["theme_fondation_lune"]["conclusion"] != d["theme_corps_lune"]["conclusion"]
    assert d["theme_fondation_soleil"]["question"] != d["theme_corps_soleil"]["question"]


def test_didactique_en_memes_cles_que_fr():
    fr = Z.didactique("fr")
    en = Z.didactique("en")
    assert set(fr.keys()) == set(en.keys()), (
        f"clés divergentes : {set(fr)^set(en)}")
    for k in en:
        e = en[k]
        assert e.get("question"), f"{k} EN sans question"
        assert isinstance(e.get("domaines"), list) and len(e["domaines"]) >= 3, (
            f"{k} EN domaines invalides")
        assert e.get("conclusion"), f"{k} EN sans conclusion"


def test_didactique_en_valeurs_differentes_de_fr():
    """Les valeurs EN sont bien traduites (pas un copier-coller)."""
    fr = Z.didactique("fr")
    en = Z.didactique("en")
    diff = [k for k in fr if fr[k]["question"] == en[k]["question"]]
    assert not diff, f"entrées EN non traduites : {diff[:3]}"
