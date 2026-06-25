"""Préparer un texte POUR LA VOIX — nettoyage avant synthèse (Piper & co).

Un texte d'assistant est écrit pour l'ÉCRAN : markdown (`**gras**`, titres `#`, listes
`- `), emoji, liens, blocs de code, tableaux, horodatages de chapitres… Lu tel quel par un
moteur TTS, ça « parasite » la voix (symboles épelés, puces lues, code récité, URLs à
rallonge). Ce module transforme ce texte en PROSE PARLABLE :

  • on RETIRE ce qui ne se dit pas (symboles markdown, emoji, liens, code, horodatages) ;
  • on GARDE tout le CONTENU et la ponctuation naturelle (. , ; : ! ?) — ce sont les pauses
    et l'intonation qui rendent la lecture vivante, on n'y touche pas ;
  • les listes et titres deviennent des phrases (terminées par un point → pause naturelle).

Fonction pure, sans I/O : facile à tester, appelée en UN point (moteur.synthetiser) pour que
TOUTE synthèse en profite. Si après nettoyage il ne reste rien (texte tout en emoji/symboles),
on rend une chaîne vide — l'appelant fera son repli honnête (placeholder, pas de fausse voix).
"""
import re
import unicodedata

# Blocs de code clôturés ```…``` (multi-lignes) — on ne RÉCITE jamais du code à voix haute.
_BLOC_CODE = re.compile(r"```.*?```", re.DOTALL)
# Code en ligne `comme ça` → on garde le texte intérieur, sans les accents graves.
_CODE_LIGNE = re.compile(r"`([^`]*)`")
# Images ![alt](url) puis liens [texte](url) → on garde le libellé lisible, pas l'URL.
_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LIEN_MD = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# URLs nues (http(s):// ou www.) → illisibles à l'oral, on les retire.
_URL_NUE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
# Horodatages de chapitres : 0:34, 12:05, 1:23:45 → « zéro deux trente » ne sert à rien à l'oral.
_HORODATAGE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
# Filets horizontaux markdown : ---, ***, ___ sur une ligne.
_FILET = re.compile(r"^\s*([-*_])\1{2,}\s*$", re.MULTILINE)
# Marqueur de liste / citation / titre en DÉBUT de ligne (puces, numéros, >, #).
_PUCE = re.compile(r"^\s{0,3}(?:[-*+•·–—]\s+|\d{1,3}[.)]\s+|>\s?|#{1,6}\s+)", re.MULTILINE)
# Emphase markdown : on retire les marqueurs **, __, *, _, ~~ (en gardant le texte).
_EMPHASE = re.compile(r"(\*\*|__|~~|\*|_)")
# Symboles résiduels qui s'épellent mal (table |, #, =, surplus de *_`~^).
_SYMBOLES = re.compile(r"[|#=`~^*_]+")
# Tirets « décoratifs » : runs (--, ---) et tiret isolé entre espaces (puce/séparateur).
# On préserve le trait d'union DANS un mot (« vas-tu ») : il n'a pas d'espace autour.
_TIRETS = re.compile(r"[-–—]{2,}|(?<=\s)[-–—](?=\s)|^[-–—](?=\s)|(?<=\s)[-–—]$")
# Espaces multiples ; espace AVANT une ponctuation française fine.
_ESPACES = re.compile(r"[ \t ]{2,}")
_ESPACE_AVANT_PONCT = re.compile(r"\s+([,.])")
# Ponctuation de fin de phrase (pour décider d'ajouter un point en jointure de lignes).
_FIN_PHRASE = re.compile(r"[.!?…:;]$")


def _sans_emoji(texte: str) -> str:
    """Retire emoji & pictogrammes (catégorie Unicode « So », plus variation selectors et ZWJ).

    On s'appuie sur la catégorie Unicode plutôt que sur des plages codées en dur : robuste aux
    nouveaux emoji. On garde lettres accentuées, chiffres, ponctuation et symboles utiles
    (€, %, &, +) — eux SE DISENT."""
    utiles = {"€", "%", "&", "+", "<", ">", "$", "£", "©", "®", "°"}
    sortie = []
    for ch in texte:
        if ch in utiles:
            sortie.append(ch)
            continue
        cat = unicodedata.category(ch)
        # So = autre symbole (emoji, pictos) ; Cf = format (ZWJ, variation selectors) ; Sk modificateurs.
        if cat in ("So", "Cf", "Sk"):
            continue
        sortie.append(ch)
    return "".join(sortie)


def pour_la_voix(texte: str) -> str:
    """Transforme un texte écrit en prose parlable. Idempotent sur un texte déjà propre :
    une phrase simple (« Bonjour ») ressort identique."""
    if not texte:
        return ""

    t = _BLOC_CODE.sub(" ", texte)          # 1. on enlève les blocs de code entiers
    t = _CODE_LIGNE.sub(r"\1", t)           #    le code en ligne garde son texte
    t = _IMAGE_MD.sub(r"\1", t)             # 2. images/liens → libellé seul (sans URL)
    t = _LIEN_MD.sub(r"\1", t)
    t = _URL_NUE.sub(" ", t)                #    URLs nues retirées
    t = _FILET.sub(" ", t)                  # 3. filets horizontaux
    t = _PUCE.sub("", t)                    # 4. puces / numéros / > / # en début de ligne
    t = _EMPHASE.sub("", t)                 # 5. **gras** *italique* ~~barré~~ → texte nu
    t = _HORODATAGE.sub(" ", t)             # 6. horodatages de chapitres
    t = _sans_emoji(t)                      # 7. emoji & pictogrammes

    # 8. lignes → phrases : chaque saut de ligne non terminé par une ponctuation devient un
    #    point (pause naturelle) ; les lignes vides sont absorbées.
    lignes = [l.strip() for l in t.splitlines()]
    morceaux = []
    for ligne in lignes:
        if not ligne:
            continue
        if morceaux and not _FIN_PHRASE.search(morceaux[-1]):
            morceaux[-1] += "."
        morceaux.append(ligne)
    t = " ".join(morceaux)

    t = _SYMBOLES.sub(" ", t)               # 9. symboles résiduels (tables, #, =, …)
    t = _TIRETS.sub(" ", t)                 #    tirets décoratifs (--, ---, séparateurs)
    t = _ESPACE_AVANT_PONCT.sub(r"\1", t)   # 10. recolle la ponctuation
    t = _ESPACES.sub(" ", t)
    return t.strip()
