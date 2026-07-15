"""Smoke test de la page /app (S172) — HTML bien formé, pas de dépendance réseau."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from routers.app_web import app_page


@pytest.mark.asyncio
async def test_app_page_contient_la_config_keycloak():
    resp = await app_page()
    assert resp.status_code == 200
    corps = resp.body.decode()
    assert "calendar-app" in corps
    assert "<title>" in corps


@pytest.mark.asyncio
async def test_app_page_contient_le_chargement_des_calendriers():
    resp = await app_page()
    corps = resp.body.decode()
    assert "chargerCalendriers" in corps
    assert "/calendars" in corps


@pytest.mark.asyncio
async def test_app_page_contient_la_modale_evenement():
    resp = await app_page()
    corps = resp.body.decode()
    assert "ouvrirModaleEvent" in corps
    assert "enregistrerEvent" in corps


@pytest.mark.asyncio
async def test_app_page_contient_le_bouton_inviter():
    resp = await app_page()
    corps = resp.body.decode()
    assert "ouvrirModaleInviter" in corps
    assert "/invitations" in corps


@pytest.mark.asyncio
async def test_app_page_le_script_est_du_js_syntaxiquement_valide():
    """Filet de sécurité : les tests ci-dessus ne vérifient que la présence de sous-chaînes,
    pas que le <script> inline soit du JS valide (cf. bug quelqu\\'un double-backslash S172
    qui cassait TOUT le script — non détecté par les tests substring-only)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node introuvable dans cet environnement — vérification syntaxique sautée")

    resp = await app_page()
    corps = resp.body.decode()
    m = re.search(r"<script>(.*)</script>", corps, re.DOTALL)
    assert m, "balise <script> introuvable dans la page /app"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, dir=tempfile.gettempdir()) as f:
        f.write(m.group(1))
        chemin = f.name
    try:
        r = subprocess.run([node, "--check", chemin], capture_output=True, text=True)
        assert r.returncode == 0, f"JS invalide dans /app :\n{r.stderr}"
    finally:
        Path(chemin).unlink(missing_ok=True)
