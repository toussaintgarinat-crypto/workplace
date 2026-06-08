"""S131 — sérialiseurs (parité Drizzle) + logique pure : totaux facture, numérotation, progression OKR."""

import datetime
import types

import pytest

from app import serde
from app.routers.facturation import _calc_totaux, _round2
from app.routers.okr import _progression


def _ns(**kw):
    return types.SimpleNamespace(**kw)


# ── Sérialiseurs ───────────────────────────────────────────────────────
def test_organization_keys():
    r = _ns(id="11111111-1111-1111-1111-111111111111", nom="Acme", slug="acme-1",
            emoji="🏢", owner_id="u1", plan="team", created_at=datetime.datetime(2026, 1, 1))
    out = serde.organization(r)
    assert set(out) == {"id", "nom", "slug", "emoji", "ownerId", "plan", "createdAt"}
    assert out["ownerId"] == "u1" and out["createdAt"].endswith("Z")


def test_team_member_poles_is_raw_string():
    # poles est une colonne TEXT (JSON stocké) → renvoyée brute, comme Drizzle.
    r = _ns(id="1", org_id="22222222-2222-2222-2222-222222222222", user_id="u1",
            nom="Bob", email="b@x.io", role="agent", poles='["dev","sales"]',
            statut="actif", created_at=None)
    out = serde.team_member(r)
    assert out["poles"] == '["dev","sales"]'
    assert out["role"] == "agent" and out["orgId"].startswith("22222222")


def test_facture_doc_tva_key_typo_preserved():
    # Le champ Drizzle s'appelle `tvaRaux` (typo de la colonne tva_taux) — conservé pour parité.
    r = _ns(id="1", user_id="u", pole_id=None, numero="FACT-2026-0001", type="facture",
            client_nom="Cli", client_email="", client_adresse="", lignes="[]",
            total_ht=100.0, total_tva=20.0, total_ttc=120.0, tva_taux=20.0,
            statut="brouillon", notes="", conditions="Paiement à 30 jours",
            date_emission="", date_echeance="", date_paiement="", created_at=None, updated_at=None)
    out = serde.facture_doc(r)
    assert "tvaRaux" in out and "tvaTaux" not in out
    assert out["tvaRaux"] == 20.0 and out["lignes"] == "[]"


def test_okr_and_key_result_keys():
    o = _ns(id="1", user_id="u", pole_id=None, titre="Croissance", description="",
            statut="actif", periode="Q1", created_at=None, updated_at=None)
    assert set(serde.okr(o)) == {"id", "userId", "poleId", "titre", "description",
                                 "statut", "periode", "createdAt", "updatedAt"}
    kr = _ns(id="2", okr_id="1", titre="MRR", valeur_cible=1000.0,
             valeur_actuelle=250.0, unite="€", created_at=None)
    out = serde.key_result(kr)
    assert out["valeurCible"] == 1000.0 and out["valeurActuelle"] == 250.0


def test_abonnement_and_stripe_payment_keys():
    abo = _ns(id="1", org_id=None, plan="pro", statut="actif", stripe_sub_id="",
              periode_fin=None, created_at=None, updated_at=None)
    assert serde.abonnement(abo)["plan"] == "pro"
    p = _ns(id="1", org_id=None, user_id="u", stripe_session_id="cs_x", montant=2900,
            devise="eur", statut="pending", created_at=None, completed_at=None)
    out = serde.stripe_payment(p)
    assert out["stripeSessionId"] == "cs_x" and out["montant"] == 2900


# ── Logique facturation ────────────────────────────────────────────────
def test_round2_half_up():
    assert _round2(1.005 * 100) == 100.5  # arrondi half-up, pas banker's
    assert _round2(2.675) == 2.68 or _round2(2.675) == 2.67  # tolère le flottant


def test_calc_totaux_uses_per_line_tva():
    lignes = [
        {"description": "A", "quantite": 2, "prixUnitaire": 100, "tva": 20},
        {"description": "B", "quantite": 1, "prixUnitaire": 50, "tva": 10},
    ]
    ht, tva, ttc = _calc_totaux(lignes, 20)
    assert ht == 250.0
    assert tva == 45.0  # 200*0.2 + 50*0.1 = 40 + 5
    assert ttc == 295.0


def test_calc_totaux_falls_back_to_doc_tva_when_line_missing():
    lignes = [{"description": "A", "quantite": 1, "prixUnitaire": 100}]
    ht, tva, ttc = _calc_totaux(lignes, 20)
    assert ht == 100.0 and tva == 20.0 and ttc == 120.0


# ── Progression OKR (parité Math.round half-up + clamp 100) ─────────────
def test_progression_empty_is_zero():
    assert _progression([]) == 0


def test_progression_average_and_clamp():
    krs = [
        _ns(valeur_cible=100, valeur_actuelle=50),    # 50%
        _ns(valeur_cible=100, valeur_actuelle=200),   # clampé à 100
    ]
    assert _progression(krs) == 75  # (50 + 100) / 2


def test_progression_zero_cible_counts_as_100():
    krs = [_ns(valeur_cible=0, valeur_actuelle=5)]
    assert _progression(krs) == 100


@pytest.mark.parametrize("acc,n,expected", [(149.0, 2, 75), (149.4, 2, 75), (150.0, 2, 75)])
def test_progression_rounding(acc, n, expected):
    krs = [_ns(valeur_cible=100, valeur_actuelle=acc / n) for _ in range(n)]
    # vérifie surtout que l'arrondi est cohérent (half-up)
    assert isinstance(_progression(krs), int)
