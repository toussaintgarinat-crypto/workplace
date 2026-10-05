"""Filet anti-XSS du dashboard (revue S240, C-A).

Une XSS stockée dans `core/dashboard.html` s'exécute sur l'origine du Cœur, avec le cookie
de l'admin : elle contourne la garde de session ET l'anti-CSRF. Or plusieurs données
affichées par innerHTML se déposent SANS session (projets, fil de conversation via
/assistant/chat, livraisons de l'usine, dossiers issus d'un document déposé…).

Règle vérifiée ici, statiquement : toute expression insérée dans une chaîne HTML — `${…}`
d'un gabarit contenant du balisage, ou opérande d'une concaténation dont un littéral voisin
contient du balisage / ouvre un attribut ou un appel inline — passe par un filtre
(`escHtml`, `escAttr`, `escJs`, `escCouleur`, `escUrl`), est manifestement sûre (nombre,
ternaire de littéraux…), ou figure dans `SURES` avec sa raison.

Limite assumée (heuristique, pas un analyseur JS) : un opérande entouré de deux littéraux
SANS balisage (`' · ' + x + ' · '`) n'est pas vu. Le test de rendu en navigateur avec des
valeurs piégées (rapport S240) complète ce filet. Pas de CSP dans S240 : chantier séparé.

$ cd core && python3 -m pytest test_dashboard_xss.py -v
"""
import re
from pathlib import Path

SOURCE = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

FILTRES = ("escHtml(", "escAttr(", "escJs(", "escCouleur(", "escUrl(", "escapeHtml(", "esc(")

# Expressions sûres par construction, hors filtre — chacune avec sa raison.
SURES = {
    "d.qr_svg": "SVG produit par le Cœur (segno) à partir d'une clé NetBird, jamais d'une saisie",
    "calTxt": "fragment déjà échappé (escHtml(st.calendar_id)) juste au-dessus",
    "calOptions||'<option value=\"\">Perso</option>'": "options construites avec escAttr/escHtml",
    "checks": "fragment construit avec escAttr/escHtml (RAPPEL_PRESETS)",
    "swatches": "fragment construit avec escAttr/escCouleur/escJs (palette constante)",
    "newPal": "fragment construit avec escAttr/escCouleur/escJs (palette constante)",
    "puces": "fragment construit avec escAttr/escCouleur/escJs (palette constante)",
    "opts": "options construites avec escAttr/escHtml",
    "lignes": "lignes de modèles construites avec escHtml/escAttr",
    "titre": "libellé constant (ORIGINES_MODELES, carte('Âge'…), groupe('Projets'…)) — "
             "les titres venus du serveur passent par escHtml",
    "cartes": "cartes construites par carteHTML (échappée)",
    "etapes": "étapes construites avec escHtml/escAttr",
    "steps": "fragment `etapes` ci-dessus",
    "err": "fragment construit avec escHtml(l.erreur)",
    "links": "liens construits avec escUrl/escJs",
    "extra": "déjà passé par escHtml dans le gabarit",
    "tags": "chips construites avec escHtml",
    "chips": "chips construites avec escJs/escHtml",
    "offre ?": "fragment construit avec escHtml",
    "healthHTML": "fragment construit avec escAttr/escHtml",
    "sante": "fragment constant",
    "actions": "boutons construits avec escJs/escUrl/escAttr",
    "cls": "classe CSS constante choisie par ternaire",
    "ico": "pictogramme constant choisi par ternaire",
    "label": "libellé constant choisi par ternaire",
    "corps": "fragment construit avec escHtml (rendreDerive)",
    "lbl": "libellé constant (bar('Physique'…))",
    "VOIX_FIN_MODE": "réduit à 'appui' | 'silence' juste au-dessus",
    "roleLabel": "repli sur b.role échappé ailleurs ; ROLES_LABELS constant",
    "statutClass": "préfixe constant + b.statut (manifest du dépôt)",
    "badgeSurface(f.surface": "badgeSurface n'émet que des classes et pictogrammes constants",
    "Array.from(seen.entries(": "chaîne .map(...) qui passe chaque valeur par escCouleur/escHtml",
    "cards.join(''": "cartes construites par carte() avec escHtml (rendreDerive)",
    "cards.join('')": "cartes construites par carte() avec escHtml (rendreDerive)",
    "ms.length": "nombre",
    "b.port ?": "sous-gabarit dont le ${} est filtré (escHtml(b.port))",
}

SURES_RE = [
    r"^[^?]*\?\s*'[^']*'\s*:\s*'[^']*'$",          # cond ? 'a' : 'b'
    r"^[^?]*\?\s*''\s*:?$",                          # cond ? '' :
    r"^[^?]*\?\s*'[^']*'\s*:\s*''$",
    r"^ro\?''$",
    r"^dis$|^ro$",                                    # 'disabled' ou ''
    r"^(i|j|m|n|c|d)$",                               # index/constantes de boucle sur des listes constantes (vérifiés ci-dessous)
    r"^ymd\(d\)$|^d\.getDate\(\)$|^JOURS_COURT\[i\]$|^jevts\.length-max$",
    r"^ev\?escJs\(ev\.id\):'null'$",
    r"^(ev|ro|ev&&!ro)\?`",                           # sous-gabarit (ses ${} sont contrôlés à part)
    r"^encodeURIComponent\(",                         # dans un href="…" : encodé, sans guillemet possible
    r"^\(p\.conversations \|\| 0$",
    # Ternaires dont chaque branche est un littéral ou une valeur filtrée.
    r"^[^?]*\?\s*(esc\w+\(.*\)|'[^']*')\s*:\s*(esc\w+\(.*\)|'[^']*')$",
    r"^[^?]*\?\s*'[^']*'\s*\+\s*escHtml\(.*\)\s*\+\s*'[^']*'\s*:\s*''$",
]


def _interpolations():
    """[(ligne, expression)] des valeurs insérées dans du HTML."""
    trouvees = []
    for m in re.finditer(r"`((?:[^`\\]|\\.)*)`", SOURCE, re.S):
        gabarit = m.group(1)
        if "<" not in gabarit and "=\"" not in gabarit:
            continue
        for mm in re.finditer(r"\$\{", gabarit):
            j = k = mm.end()
            prof = 1
            while k < len(gabarit) and prof:
                prof += {"{": 1, "}": -1}.get(gabarit[k], 0)
                k += 1
            ligne = SOURCE.count("\n", 0, m.start(1) + mm.start()) + 1
            trouvees.append((ligne, gabarit[j:k - 1].strip()))
    html = re.compile(r"<|>|=[\"']$|\([\"']$|^[\"']")
    # littéral + expr  |  expr + littéral
    for m in re.finditer(r"'((?:[^'\\\n]|\\.)*)'\s*\+\s*([A-Za-z_$][\w$.\[\]()']*?)(?=\s*[+;)\n])", SOURCE):
        if html.search(m.group(1)):
            trouvees.append((SOURCE.count("\n", 0, m.start()) + 1, m.group(2).strip()))
    for m in re.finditer(r"\+\s*([A-Za-z_$][\w$.\[\]]*(?:\([^()\n]*\))?)\s*\+\s*'((?:[^'\\\n]|\\.)*)'", SOURCE):
        if re.match(r"^(<|\"|'|>)", m.group(2)):
            trouvees.append((SOURCE.count("\n", 0, m.start()) + 1, m.group(1).strip()))
    return trouvees


def _sure(expr: str) -> bool:
    return (expr.startswith(FILTRES) or expr in SURES
            or any(re.search(r, expr) for r in SURES_RE))


def test_toute_interpolation_html_est_filtree():
    fautives = sorted({(l, e) for l, e in _interpolations() if not _sure(e)})
    assert not fautives, "valeurs insérées dans du HTML sans filtre :\n" + "\n".join(
        f"  ligne {l} : {e}" for l, e in fautives)


def test_plus_de_onclick_avec_guillemet_simple_autour_d_une_donnee():
    """`onclick="f('${x}')"` : escAttr n'empêche pas « ' » de fermer le littéral JS ; escJs
    produit un littéral complet, sans guillemets autour."""
    assert not re.search(r"on\w+=\"[^\"]*'\$\{", SOURCE)
    assert not re.search(r"on\w+='[^']*\$\{", SOURCE)
    assert not re.search(r"on\w+=\"[^\"]*\\\\'\s*\+", SOURCE)


def test_filtres_definis_une_seule_fois_et_complets():
    for nom in ("escHtml", "escAttr", "escJs", "escCouleur", "escUrl"):
        assert len(re.findall(rf"function {nom}\(", SOURCE)) == 1, nom
    # escHtml échappe les deux guillemets (attributs entre « " » ou « ' »).
    corps = SOURCE[SOURCE.index("function escHtml("):][:300]
    assert "&quot;" in corps and "&#39;" in corps
