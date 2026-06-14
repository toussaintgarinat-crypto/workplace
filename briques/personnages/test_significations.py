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
