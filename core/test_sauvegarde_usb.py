import asyncio

import httpx
import pytest

import sauvegarde_usb


def _cadre_exec(type_flux: int, charge: bytes) -> bytes:
    """Construit une trame du format multiplexé Docker exec (Tty=false) :
    1 octet type + 3 octets réservés + 4 octets longueur (big-endian) + charge."""
    entete = bytes([type_flux, 0, 0, 0]) + len(charge).to_bytes(4, "big")
    return entete + charge


def test_demultiplexer_isole_stdout():
    brut = _cadre_exec(1, b"bonjour") + _cadre_exec(2, b"ignore-moi") + _cadre_exec(1, b" monde")
    assert sauvegarde_usb._demultiplexer(brut) == b"bonjour monde"


def test_demultiplexer_flux_vide():
    assert sauvegarde_usb._demultiplexer(b"") == b""


def test_exec_renvoie_code_et_stdout():
    # Async via asyncio.run — motif déjà en usage dans toute la suite core/ (cf.
    # core/test_muscle.py, core/test_amelioration_outils.py), pas de marqueur pytest.
    appels = []

    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(request.url.path)
        if request.url.path == "/containers/abc123/exec":
            return httpx.Response(200, json={"Id": "exec1"})
        if request.url.path == "/exec/exec1/start":
            return httpx.Response(200, content=_cadre_exec(1, b"ok\n"))
        if request.url.path == "/exec/exec1/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {request.url.path}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb._exec(client, "abc123", ["echo", "ok"])

    code, sortie = asyncio.run(go())
    assert code == 0
    assert sortie == b"ok\n"
    assert appels == ["/containers/abc123/exec", "/exec/exec1/start", "/exec/exec1/json"]
