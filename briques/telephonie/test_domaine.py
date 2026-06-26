"""Domaine pur de la téléphonie — E.164, segmentation SMS, transitions (hors-ligne)."""
import pytest

import domaine


@pytest.mark.parametrize("brut,attendu", [
    ("+33612345678", "+33612345678"),
    ("+33 6 12 34 56 78", "+33612345678"),
    ("+1 (201) 555-0123", "+12015550123"),
])
def test_normaliser_numero_ok(brut, attendu):
    assert domaine.normaliser_numero(brut) == attendu


@pytest.mark.parametrize("mauvais", ["0612345678", "+0123", "", "abc", "+33"])
def test_normaliser_numero_invalide(mauvais):
    assert not domaine.numero_valide(mauvais)
    with pytest.raises(ValueError):
        domaine.normaliser_numero(mauvais)


def test_sms_valide_borne():
    assert domaine.sms_valide("coucou")
    assert not domaine.sms_valide("")
    assert not domaine.sms_valide("x" * (domaine.SMS_MAX + 1))


def test_segments_sms():
    assert domaine.segments_sms("") == 0
    assert domaine.segments_sms("x" * 160) == 1
    assert domaine.segments_sms("x" * 161) == 2          # bascule en concaténé (153/segment)
    assert domaine.segments_sms("x" * 306) == 2
    assert domaine.segments_sms("x" * 307) == 3


def test_transitions_sms():
    assert domaine.transition_sms_permise(domaine.SMS_FILE, domaine.SMS_ENVOYE)
    assert domaine.transition_sms_permise(domaine.SMS_FILE, domaine.SMS_ECHOUE)
    assert not domaine.transition_sms_permise(domaine.SMS_ENVOYE, domaine.SMS_FILE)
    assert not domaine.transition_sms_permise(domaine.SMS_RECU, domaine.SMS_ENVOYE)


def test_transitions_appel():
    assert domaine.transition_appel_permise(domaine.APPEL_INITIE, domaine.APPEL_EN_COURS)
    assert domaine.transition_appel_permise(domaine.APPEL_EN_COURS, domaine.APPEL_TERMINE)
    assert not domaine.transition_appel_permise(domaine.APPEL_TERMINE, domaine.APPEL_EN_COURS)
