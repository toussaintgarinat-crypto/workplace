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

Vérifié aussi (revue S240, M1) : chaque opérande d'une concaténation ou d'un ternaire DANS
un `${…}` ; l'argument de `insertAdjacentHTML` ; toute affectation `.href =` / `.src =`
(filtrée par `urlSure`/`escUrl`, littérale, ou listée).

ANGLES MORTS CONNUS (heuristique, pas un analyseur JS) :
- un opérande entouré de deux littéraux SANS balisage (`' · ' + x + ' · '`) ;
- un gabarit `…` imbriqué dans un `${…}` (le découpage par accents graves s'y perd) ;
- une valeur construite plus haut dans une variable intermédiaire puis insérée (`html`,
  `lignes`…) : seule la variable est vue — d'où `SURES`, qui dit pour chacune comment elle
  est construite ;
- `setAttribute('href'|'src'|'on…', x)`, `outerHTML`, `document.write`, `srcdoc` (aucun
  aujourd'hui, non détectés s'ils apparaissent) ;
- les fronts de briques proxifiés sur l'origine du Cœur (studio-app, mail-app, ateliers) :
  hors de ce fichier, même périmètre de sécurité (cf. auth.verifier_anti_csrf).
Le test de rendu en navigateur avec des valeurs piégées (rapport S240) complète ce filet.
Pas de CSP dans S240 : chantier séparé.

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
    "dis": "constante locale 'disabled' ou ''",
    "ro": "booléen local (lecture seule)",
}

# Affectations d'URL (`.href =` / `.src =`) sûres par construction.
URLS_SURES = {
    "'/auth/logout'": "littéral",
    "url + (url.includes('?') ? '&' : '?') + '_=' + Date.now()":
        "ouvrirCreation(url) : URL de tuile injectée par le Cœur (urls_ui, env), jamais une saisie",
    "url": "ouvrirCreation(url) : idem",
    "FORGE_UI_URL": "injectée par le Cœur (routers/dashboard.py, env/hôte de la requête)",
    "GEO_UI_URL": "idem", "DEV_IDE_URL": "idem", "GATEWAY_UI_URL": "idem",
    "URL.createObjectURL(new Blob([texte], { type: 'text/plain' }))": "blob: local (export .env)",
}

SURES_RE = [
    r"^[^?]*\?\s*'[^']*'\s*:\s*'[^']*'$",          # cond ? 'a' : 'b'
    r"^[^?]*\?\s*''\s*:?$",                          # cond ? '' :
    r"^[^?]*\?\s*'[^']*'\s*:\s*''$",
    r"^ro\?''$",
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


def _decouper(expr: str, seps: str) -> list[str]:
    """Découpe `expr` sur les séparateurs de PREMIER niveau (hors parenthèses, crochets,
    accolades et chaînes)."""
    morceaux, prof, cour, guill = [], 0, "", None
    for ch in expr:
        if guill:
            cour += ch
            if ch == guill:
                guill = None
            continue
        if ch in "'\"`":
            guill = ch
        elif ch in "([{":
            prof += 1
        elif ch in ")]}":
            prof -= 1
        elif ch in seps and prof == 0:
            morceaux.append(cour.strip())
            cour = ""
            continue
        cour += ch
    morceaux.append(cour.strip())
    return morceaux


_LITTERAL = re.compile(r"^('[^']*'|\"[^\"]*\"|`[^`]*`|-?\d+(\.\d+)?)$")


def _atome_sur(a: str) -> bool:
    return (not a or bool(_LITTERAL.match(a)) or a.startswith(FILTRES) or a in SURES
            or any(re.search(r, a) for r in SURES_RE))


def _sure(expr: str) -> bool:
    if expr.startswith(FILTRES) and _decouper(expr, "+") == [expr]:
        return True
    if expr in SURES or any(re.search(r, expr) for r in SURES_RE):
        return True
    # Revue S240, M1 : on descend dans l'expression — ternaire (la CONDITION n'est pas
    # affichée, seules les branches le sont) puis chaque opérande d'une concaténation.
    if "?" in expr:
        tete = _decouper(expr, "?")
        if len(tete) >= 2:
            branches = _decouper("?".join(tete[1:]), ":")
            return all(_sure(b) for b in branches)
    operandes = _decouper(expr, "+")
    if len(operandes) > 1:
        return all(_atome_sur(o) for o in operandes)
    return _atome_sur(expr)


def test_toute_interpolation_html_est_filtree():
    fautives = sorted({(l, e) for l, e in _interpolations() if not _sure(e)})
    assert not fautives, "valeurs insérées dans du HTML sans filtre :\n" + "\n".join(
        f"  ligne {l} : {e}" for l, e in fautives)


def test_insert_adjacent_html_filtre():
    for m in re.finditer(r"insertAdjacentHTML\(\s*'[^']*'\s*,\s*", SOURCE):
        suite = SOURCE[m.end():m.end() + 1]
        # Seul un gabarit `…` est admis : ses ${} passent par test_toute_interpolation…
        assert suite == "`", SOURCE[m.start():m.start() + 120]


def test_affectations_href_src_filtrees():
    fautives = []
    for m in re.finditer(r"\.(href|src)\s*=\s*([^;\n]+?)\s*;", SOURCE):
        val = m.group(2).strip()
        if val.startswith(("urlSure(", "escUrl(")) or val in URLS_SURES or _LITTERAL.match(val):
            continue
        fautives.append((SOURCE.count("\n", 0, m.start()) + 1, val))
    assert not fautives, f"href/src non filtrés : {fautives}"


def test_url_sure_refuse_protocoles_et_chemins_ambigus():
    """Revue S240, M2 : `/\\evil` est lu `//evil` par les navigateurs (autre hôte)."""
    corps = SOURCE[SOURCE.index("function urlSure("):].split("\n", 1)[0]
    motif = re.search(r"/(\^.*?)/i\.test", corps).group(1)
    rx = re.compile(motif, re.I)
    for ok in ("/brique-fichiers/x.png", "https://exemple.fr/a", "http://192.168.1.89:5100/"):
        assert rx.search(ok), ok
    for ko in ("//evil.example/x", "/\\evil.example/x", "javascript:alert(1)",
               "data:text/html,x", " /x", "JaVaScRiPt:x"):
        assert not rx.search(ko), ko


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
