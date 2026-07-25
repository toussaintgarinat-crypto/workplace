"""Tests — moteur_clamav.py.

Le protocole clamd (INSTREAM) amont (scanners/clamav.py de suitenumerique/file-scanner,
MIT) est mocké ici au niveau du client — comme rendu_pdf.py mocke WeasyPrint (cf. plan
S194) : ces tests tournent OFFLINE, sans démon ClamAV réel."""
import io

import clamd
import pytest

import moteur_clamav as M


class _FauxClientPropre:
    def instream(self, fileobj):
        return {"stream": ("OK", None)}

    def ping(self):
        return "PONG"


class _FauxClientMalware:
    def instream(self, fileobj):
        return {"stream": ("FOUND", "Eicar-Test-Signature")}


class _FauxClientErreur:
    def instream(self, fileobj):
        return {"stream": ("ERROR", "Memory allocation failed")}


class _FauxClientInjoignable:
    def instream(self, fileobj):
        raise ConnectionRefusedError("connexion refusée")

    def ping(self):
        raise ConnectionRefusedError("connexion refusée")


class _FauxClientBufferTropGros:
    def instream(self, fileobj):
        raise clamd.BufferTooLongError("fichier trop volumineux pour le scan")


def test_scanner_fichier_propre(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientPropre())
    verdict = M.scanner(io.BytesIO(b"contenu inoffensif"))
    assert verdict.propre is True
    assert verdict.raison is None


def test_scanner_detecte_malware(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientMalware())
    verdict = M.scanner(io.BytesIO(b"faux malware"))
    assert verdict.propre is False
    assert verdict.raison == "Eicar-Test-Signature"


def test_scanner_erreur_clamd_leve_indisponible(monkeypatch):
    # Un ERROR clamd = fichier NON scanné en entier -> jamais "propre" (fail-closed, R6)
    monkeypatch.setattr(M, "_client", lambda: _FauxClientErreur())
    with pytest.raises(M.MoteurIndisponible):
        M.scanner(io.BytesIO(b"x"))


def test_scanner_connexion_refusee_leve_indisponible(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientInjoignable())
    with pytest.raises(M.MoteurIndisponible):
        M.scanner(io.BytesIO(b"x"))


def test_scanner_buffer_trop_gros_leve_indisponible(monkeypatch):
    # BufferTooLongError (sous-classe de ResponseError) = fichier NON scanné en entier
    # -> jamais "propre" (fail-closed, R6)
    monkeypatch.setattr(M, "_client", lambda: _FauxClientBufferTropGros())
    with pytest.raises(M.MoteurIndisponible):
        M.scanner(io.BytesIO(b"x"))


def test_ping_ok(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientPropre())
    assert M.ping() is True


def test_ping_ko_si_injoignable(monkeypatch):
    monkeypatch.setattr(M, "_client", lambda: _FauxClientInjoignable())
    assert M.ping() is False
