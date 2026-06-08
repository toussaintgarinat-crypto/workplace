SUMMARIZE_CLUSTER = """Tu es le jardinier d'un système de mémoire personnelle.
Analyse ces {count} souvenirs liés et propose un résumé concis qui les condense.
Format : {title, summary, tags}"""

MERGE_DUPLICATES = """Ces deux souvenirs semblent similaires (score: {score}).
Propose une fusion : titre, contenu combiné, propriétés à garder."""

SUGGEST_IPCRa = """Ce souvenir est en stage "{current_stage}" depuis {days} jours.

{content}

Propose un stage de destination (projet/casquette/ressource/archive)
et justifie en une phrase."""

ARCHIVE_DECISION = """Ce souvenir est en archive depuis longtemps et n'a pas été consulté.
Décide si on doit : le passer en archive froide, ou le laisser en archive.

{content}"""

INFERENCE_LINKS = """Un nouveau souvenir a été créé :
{content}

Parmi les souvenirs existants suivants, détecte ceux qui pourraient être liés :
{existing}

Pour chaque lien potentiel, précise le type (related/cause/part_of/references/contradicts)."""
