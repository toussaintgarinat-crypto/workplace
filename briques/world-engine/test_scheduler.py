"""Tests du scheduler parallélisé (Sprint E) — même motif que
test_horloge_moteur.py : ticks mockés via monkeypatch, jamais de vraie
boucle de fond (HORLOGE_SCHEDULER_DESACTIVE=1 posé dans conftest.py)."""
import logging
import time

import pytest

import horloge_moteur
import main


@pytest.mark.asyncio
async def test_executer_passage_execute_les_mondes_dus_en_parallele(monkeypatch):
    import asyncio

    ordre_debut = []
    ordre_fin = []

    async def _tick_lent(monde_id, cle_api_val):
        ordre_debut.append(monde_id)
        await asyncio.sleep(0.2)
        ordre_fin.append(monde_id)
        return {"avertissements": []}

    monkeypatch.setattr(horloge_moteur, "executer_tick", _tick_lent)

    dues = [
        {"monde_id": "monde-a", "cle_api": "k1"},
        {"monde_id": "monde-b", "cle_api": "k1"},
        {"monde_id": "monde-c", "cle_api": "k1"},
    ]

    debut = time.monotonic()
    await main._executer_passage(dues)
    duree = time.monotonic() - debut

    # 3 ticks de 0.2s : en série ~0.6s, en parallèle ~0.2s. Seuil à 0.45s pour
    # absorber la latence de l'environnement de test sans rendre le test friable.
    assert duree < 0.45
    assert set(ordre_debut) == {"monde-a", "monde-b", "monde-c"}
    assert set(ordre_fin) == {"monde-a", "monde-b", "monde-c"}


@pytest.mark.asyncio
async def test_executer_passage_logue_les_avertissements(monkeypatch, caplog):
    async def _tick_avec_avertissement(monde_id, cle_api_val):
        return {"avertissements": [
            "Émigration de x vers y non appliquée : verrou du pays destination "
            "indisponible (retentera au tick suivant)."
        ]}

    monkeypatch.setattr(horloge_moteur, "executer_tick", _tick_avec_avertissement)

    with caplog.at_level(logging.WARNING, logger="world-engine"):
        await main._executer_passage([{"monde_id": "monde-a", "cle_api": "k1"}])

    avertissements = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(avertissements) == 1
    assert "monde-a" in avertissements[0].message
    assert "verrou du pays destination" in avertissements[0].message


@pytest.mark.asyncio
async def test_executer_passage_isole_une_exception_sans_arreter_les_autres(monkeypatch, caplog):
    appeles = []

    async def _tick_selon_monde(monde_id, cle_api_val):
        appeles.append(monde_id)
        if monde_id == "monde-en-echec":
            raise RuntimeError("panne simulée")
        return {"avertissements": []}

    monkeypatch.setattr(horloge_moteur, "executer_tick", _tick_selon_monde)

    dues = [
        {"monde_id": "monde-en-echec", "cle_api": "k1"},
        {"monde_id": "monde-ok", "cle_api": "k1"},
    ]

    with caplog.at_level(logging.ERROR, logger="world-engine"):
        await main._executer_passage(dues)  # ne doit lever aucune exception

    assert set(appeles) == {"monde-en-echec", "monde-ok"}
    erreurs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(erreurs) == 1
    assert "monde-en-echec" in erreurs[0].message
