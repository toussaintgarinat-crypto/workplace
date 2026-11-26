"""Réécriture du nom de base dans UNE variable d'un fichier d'environnement (S247 2b).
Fonction pure : le reste du texte est recopié octet pour octet. Les erreurs ne citent jamais
la valeur (elle contient un mot de passe) ni le texte de l'environnement."""
import re


def reecrire_env(env: str, variable: str, ancienne: str, nouvelle: str) -> str:
    """Remplace UNIQUEMENT le nom de base dans l'URL de `variable`. Lève ValueError (sans citer
    la valeur) si la variable manque, est ambiguë ou ne pointe pas sur `ancienne`.
    Le préfixe « export » n'est pas supporté (variable considérée introuvable)."""
    lignes = (env or "").split("\n")
    motif = re.compile(r"(" + re.escape(variable) + r"=)(.*)", re.DOTALL)
    trouvees = []
    for i, l in enumerate(lignes):
        corps = l[:-1] if l.endswith("\r") else l
        m = motif.fullmatch(corps)
        if m:
            trouvees.append((i, m, l[len(corps):]))
    if len(trouvees) != 1:
        raise ValueError("variable de base introuvable ou ambiguë")
    i, m, fin = trouvees[0]
    nom, valeur = m.groups()
    guillemet = valeur[:1] if len(valeur) >= 2 and valeur[:1] in "\"'" and valeur[-1:] == valeur[:1] else ""
    coeur = valeur[1:-1] if guillemet else valeur
    # Un « ? » ou « # » non encodé dans le mot de passe rendrait la coupure ambiguë : si la
    # suite (requête/fragment) contient un « @ », l'URL est douteuse et on refuse.
    reste = re.split(r"[?#]", coeur, maxsplit=1)
    if len(reste) == 2 and "@" in reste[1]:
        raise ValueError("URL de base ambiguë")
    nv, n = re.subn(r"^(\w[\w+.-]*://[^?#]*[^/?#]/)" + re.escape(ancienne) + r"(?=$|[?#])",
                    lambda mm: mm.group(1) + nouvelle, coeur)
    if n != 1:
        raise ValueError("la variable ne pointe pas sur la base attendue")
    lignes[i] = nom + guillemet + nv + guillemet + fin
    return "\n".join(lignes)
