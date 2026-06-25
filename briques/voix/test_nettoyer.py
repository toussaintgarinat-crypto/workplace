"""Tests du nettoyage POUR LA VOIX — on retire ce qui ne se dit pas, on garde le contenu."""
import nettoyer


def n(t):
    return nettoyer.pour_la_voix(t)


def test_texte_simple_inchange():
    # Une phrase déjà propre ressort identique (pas de point ajouté, pas de casse).
    assert n("Bonjour") == "Bonjour"
    assert n("Bonjour, comment vas-tu ?") == "Bonjour, comment vas-tu ?"


def test_vide_et_blancs():
    assert n("") == ""
    assert n("   \n\t ") == ""


def test_emphase_markdown_retiree():
    assert n("C'est **très** important et _utile_.") == "C'est très important et utile."
    assert n("~~annulé~~ fait") == "annulé fait"


def test_titres_et_puces_deviennent_phrases():
    texte = "# Résumé\n- Premier point\n- Second point"
    # Pas de « # », pas de « - » ; chaque ligne devient une phrase (pause = point).
    out = n(texte)
    assert "#" not in out and "-" not in out.split()  # plus de marqueur de puce isolé
    assert out == "Résumé. Premier point. Second point"


def test_liste_numerotee():
    assert n("1. un\n2. deux\n3. trois") == "un. deux. trois"


def test_liens_gardent_le_libelle_pas_url():
    assert n("Vois [la doc](https://exemple.fr/page) ici") == "Vois la doc ici"
    assert "http" not in n("Source : https://exemple.fr/x?y=1 voilà")


def test_emoji_retires():
    assert n("Bravo 🎉👏 c'est prêt ✅") == "Bravo c'est prêt"


def test_bloc_de_code_supprime():
    texte = "Lance ceci :\n```bash\nrm -rf /tmp\n```\npuis vérifie"
    out = n(texte)
    assert "rm -rf" not in out
    assert "Lance ceci" in out and "puis vérifie" in out


def test_code_en_ligne_garde_le_texte():
    assert n("Ouvre le fichier `main.py` maintenant") == "Ouvre le fichier main.py maintenant"


def test_horodatages_retires():
    out = n("Chapitre 1 0:34 introduction puis 1:23:45 la suite")
    assert "0:34" not in out and "1:23:45" not in out
    assert "introduction" in out and "la suite" in out


def test_tableau_pipes_nettoye():
    assert "|" not in n("| Nom | Prix |\n| --- | --- |\n| Café | 2 |")


def test_ponctuation_recollee():
    # Pas d'espace avant la ponctuation après nettoyage.
    assert n("Voici **ceci** , et cela .") == "Voici ceci, et cela."


def test_symboles_utiles_conserves():
    # €, %, & se DISENT : on les garde.
    out = n("Le total est 20 € soit 100 % du budget café & thé")
    assert "€" in out and "%" in out and "&" in out


def test_que_des_symboles_donne_vide():
    # Tout en emoji/markdown → rien à dire → chaîne vide (l'appelant fera son repli honnête).
    assert n("✨🎉 **__** ---") == ""
