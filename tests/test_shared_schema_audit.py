"""Tests du contrat partagé Audit (S119)."""
import pytest
from pydantic import ValidationError

from shared.schemas.audit import Audit


def test_audit_minimal_id_seul():
    a = Audit(id="abc")
    assert a.statut == "en_cours"
    assert not a.est_termine
    assert a.territoire is None


def test_audit_complet_et_est_termine():
    a = Audit.model_validate({
        "id": "x1", "statut": "termine", "nom_entreprise": "Cabinet Z",
        "territoire": {"secteur": "conseil"}, "flux": {"e": 1},
        "problemes": {"p": []}, "priorites": {"top": "x"},
    })
    assert a.est_termine
    assert a.nom_entreprise == "Cabinet Z"
    assert a.territoire == {"secteur": "conseil"}


def test_champs_additionnels_preserves():
    """extra=allow : un champ hors contrat ne casse pas et survit au model_dump."""
    a = Audit.model_validate({"id": "x", "date_audit": "2026-06-28", "extra_brique": 7})
    assert a.model_dump()["extra_brique"] == 7


def test_id_obligatoire():
    with pytest.raises(ValidationError):
        Audit.model_validate({"statut": "termine"})
