"""Validation des arguments d'outil contre le manifeste (S221)."""

import pytest

import guardrails_outils
import outils
import validation_args as va


# ── Le validateur pur ────────────────────────────────────────────────────────

SCHEMA = {
    "type": "object",
    "properties": {
        "destinataire": {"type": "string", "pattern": r"^.+@.+$"},
        "sujet": {"type": "string"},
        "limite": {"type": "integer", "minimum": 1, "maximum": 50},
        "score": {"type": "number"},
        "urgent": {"type": "boolean"},
        "statut": {"type": "string", "enum": ["brouillon", "envoyée", "payée"]},
        "rappels": {"type": "array", "items": {"type": "integer"}},
        "options": {"type": "object"},
    },
    "required": ["destinataire", "sujet"],
}


def categories(ecarts):
    return [e.categorie for e in ecarts]


def test_args_conformes_aucun_ecart():
    assert va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "Bonjour", "limite": 10,
         "statut": "payée", "rappels": [10, 30], "urgent": True}, SCHEMA) == []


def test_param_requis_absent():
    ecarts = va.valider_schema({"destinataire": "a@b.fr"}, SCHEMA)
    assert categories(ecarts) == ["param_requis"]
    assert "`sujet`" in ecarts[0].message and ecarts[0].bloquant


def test_param_requis_a_none_compte_comme_absent():
    """`{"sujet": None}` n'est pas une valeur — la brique recevrait un champ vide."""
    ecarts = va.valider_schema({"destinataire": "a@b.fr", "sujet": None}, SCHEMA)
    assert categories(ecarts) == ["param_requis"]


def test_type_faux_bloque():
    ecarts = va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "limite": "beaucoup"}, SCHEMA)
    assert categories(ecarts) == ["type"]
    assert ecarts[0].bloquant


def test_type_faux_court_circuite_les_autres_regles():
    """Un `limite` non numérique ne doit pas produire EN PLUS une erreur de bornes :
    un seul écart, celui qui explique la cause."""
    ecarts = va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "limite": "beaucoup"}, SCHEMA)
    assert len(ecarts) == 1


@pytest.mark.parametrize("valeur", ["10", 10, 10.0])
def test_chaine_numerique_acceptee_pour_un_entier(valeur):
    """Les arguments partent en query string (GET) ou vers un Pydantic souple : « 10 » et 10
    sont équivalents à l'arrivée. Bloquer serait un faux positif qui coûte un tour de LLM."""
    assert va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "limite": valeur}, SCHEMA) == []


def test_flottant_non_entier_refuse_pour_un_entier():
    ecarts = va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "limite": 2.5}, SCHEMA)
    assert categories(ecarts) == ["type"]


def test_booleen_refuse_la_ou_un_entier_est_attendu():
    """En Python `True` est un `int` : sans garde explicite, une vraie erreur passerait."""
    ecarts = va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "limite": True}, SCHEMA)
    assert categories(ecarts) == ["type"]


@pytest.mark.parametrize("valeur", [True, "true", "false", "1", "0"])
def test_booleen_tolere_les_formes_textuelles(valeur):
    assert va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "urgent": valeur}, SCHEMA) == []


def test_bornes_min_et_max():
    assert categories(va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "limite": 0}, SCHEMA)) == ["bornes"]
    assert categories(va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "limite": 999}, SCHEMA)) == ["bornes"]


def test_enum_hors_valeurs():
    ecarts = va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "statut": "réglée"}, SCHEMA)
    assert categories(ecarts) == ["enum"]
    assert "brouillon" in ecarts[0].message  # le LLM doit voir les choix admis


def test_motif_non_respecte():
    ecarts = va.valider_schema({"destinataire": "jean", "sujet": "x"}, SCHEMA)
    assert categories(ecarts) == ["motif"]


def test_motif_invalide_dans_le_manifest_est_ignore():
    """Un manifest mal écrit ne doit jamais bloquer un appel légitime."""
    schema = {"properties": {"x": {"type": "string", "pattern": "([a-"}}, "required": []}
    assert va.valider_schema({"x": "peu importe"}, schema) == []


def test_param_inconnu_est_signale_sans_bloquer():
    ecarts = va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "inventé": 1}, SCHEMA)
    assert categories(ecarts) == ["param_inconnu"]
    assert not ecarts[0].bloquant


def test_elements_de_tableau_mal_types_signales_sans_bloquer():
    ecarts = va.valider_schema(
        {"destinataire": "a@b.fr", "sujet": "x", "rappels": [10, "midi"]}, SCHEMA)
    assert categories(ecarts) == ["items"]
    assert not ecarts[0].bloquant


def test_schema_sans_contrainte_accepte_tout():
    assert va.valider_schema({"n_importe": "quoi"}, {"properties": {"n_importe": {}}}) == []


# ── Résolution du schéma depuis le catalogue réel ────────────────────────────

class FauxRegistre:
    def __init__(self, briques=None):
        self.briques = briques or {}


def test_schema_arguments_outil_statique():
    schema = outils.schema_arguments("lister_entreprises", FauxRegistre())
    assert schema is not None and schema["type"] == "object"


def test_schema_arguments_meta_outil_de_la_porte():
    """`competence_charger` (S90) n'est dans aucune des deux listes : il est fabriqué."""
    schema = outils.schema_arguments(outils.META_CHARGER, FauxRegistre())
    assert schema["required"] == ["nom"]


def test_schema_arguments_outil_inconnu():
    assert outils.schema_arguments("outil_qui_n_existe_pas", FauxRegistre()) is None


def test_valider_outil_inconnu_bloque():
    ecarts = va.valider("outil_qui_n_existe_pas", {}, FauxRegistre())
    assert categories(ecarts) == ["outil_inconnu"]
    assert ecarts[0].bloquant


def test_capacite_de_manifest_validee_contre_son_manifest():
    registre = FauxRegistre({"mail": {
        "nom": "mail", "port": 6030,
        "capacites": [{
            "nom": "mail_envoyer", "methode": "POST", "chemin": "/mail/envoyer",
            "description": "Envoie", "action": True,
            "params": {
                "destinataire": {"type": "string", "requis": True},
                "corps": {"type": "string", "requis": True},
                "priorite": {"type": "integer", "minimum": 1, "maximum": 3},
            }}]}})
    assert va.valider("mail_envoyer", {"destinataire": "a@b.fr", "corps": "x"}, registre) == []
    ecarts = va.valider("mail_envoyer", {"destinataire": "a@b.fr"}, registre)
    assert categories(ecarts) == ["param_requis"]
    ecarts = va.valider("mail_envoyer",
                        {"destinataire": "a@b.fr", "corps": "x", "priorite": 9}, registre)
    assert categories(ecarts) == ["bornes"]


def test_confirme_reste_accepte_sur_une_capacite_action():
    """`confirme` est ajouté par `_spec_depuis_capacite`, pas déclaré dans le manifest :
    sans ça, TOUTE action serait signalée « paramètre inconnu »."""
    registre = FauxRegistre({"mail": {
        "nom": "mail", "port": 6030,
        "capacites": [{"nom": "mail_envoyer", "methode": "POST", "chemin": "/x",
                       "action": True, "params": {}}]}})
    assert va.valider("mail_envoyer", {"confirme": True}, registre) == []


# ── Câblage dans le guardrail ────────────────────────────────────────────────

def test_guardrail_sans_valideur_inchange():
    """Comportement S143 strictement préservé quand aucun validateur n'est injecté."""
    g = guardrails_outils.Guardrail()
    assert g.before_call("quoi_que_ce_soit", {"n": 1}) == ("allow", None)


def test_guardrail_bloque_sur_ecart_bloquant():
    g = guardrails_outils.Guardrail(
        valideur=lambda n, a: [va.Ecart("param_requis", "paramètre `sujet` requis et absent")])
    action, msg = g.before_call("mail_envoyer", {})
    assert action == "block"
    assert "`sujet`" in msg and "Corrige" in msg


def test_guardrail_avertit_sans_bloquer_sur_ecart_non_bloquant():
    g = guardrails_outils.Guardrail(
        valideur=lambda n, a: [va.Ecart("param_inconnu", "paramètre `zz` inconnu")])
    action, msg = g.before_call("mail_lister", {"zz": 1})
    assert action == "warn" and "zz" in msg


def test_guardrail_survit_a_un_valideur_qui_leve():
    def valideur_casse(nom, args):
        raise RuntimeError("catalogue indisponible")

    g = guardrails_outils.Guardrail(valideur=valideur_casse)
    assert g.before_call("mail_lister", {}) == ("allow", None)


def test_guardrail_compte_les_ecarts_par_categorie():
    g = guardrails_outils.Guardrail(
        valideur=lambda n, a: [va.Ecart("type", "…"), va.Ecart("param_inconnu", "…")])
    g.before_call("x", {})
    g.before_call("y", {})
    assert g.ecarts_par_categorie() == {"type": 2, "param_inconnu": 2}


def test_guardrail_cle_supporte_des_args_non_serialisables():
    """Le LLM peut produire des arguments exotiques ; hacher ne doit jamais lever."""
    g = guardrails_outils.Guardrail()
    assert g.before_call("x", {"quand": object()})[0] == "allow"


# ── Le contrat réel : aucun faux positif sur les manifests du dépôt ──────────

def test_aucun_manifest_du_depot_ne_produit_de_schema_invalide():
    """Filet anti-régression : chaque capacité déclarée doit produire un schéma exploitable,
    et un appel vide ne doit signaler QUE des paramètres requis manquants — jamais un écart
    de type ou d'énumération, qui trahirait un manifest mal formé."""
    import registre as registre_mod

    reg = registre_mod.Registre()
    reg.charger()
    assert reg.briques, "aucune brique chargée — le test ne prouverait rien"

    for nom_brique, brique in reg.briques.items():
        for cap in (brique.get("capacites") or []):
            schema = outils.schema_arguments(cap["nom"], reg)
            if schema is None:  # nom masqué par un outil statique : hors sujet ici
                continue
            for categorie in categories(va.valider_schema({}, schema)):
                assert categorie == "param_requis", (
                    f"{nom_brique}/{cap['nom']} : écart inattendu « {categorie} » "
                    "sur un appel vide")
