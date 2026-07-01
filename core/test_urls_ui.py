"""Tests unitaires du constructeur d'URL des briques embarquées (S128).

`url_brique` doit donner la bonne URL selon d'où vient le navigateur (LAN, mesh HTTPS,
dev local) SANS figer d'IP, tout en respectant une surcharge env explicite.
"""
import os

import urls_ui


def test_lan_http_meme_ip_port_de_la_brique():
    """Host = IP LAN du HP (:5100 du dashboard) → iframe sur CETTE IP, port de la brique."""
    assert urls_ui.url_brique("STUDIO", "http", "192.168.1.89:5100") == \
        "http://192.168.1.89:6060/atelier"


def test_mesh_https_meme_ip_mesh():
    """Host = IP mesh, scheme https (derrière Caddy) → iframe HTTPS sur l'IP mesh."""
    assert urls_ui.url_brique("VOIX", "https", "100.124.248.226") == \
        "https://100.124.248.226:5985/"


def test_localhost_dev():
    assert urls_ui.url_brique("MEMOIRE", "http", "localhost:5100") == \
        "http://localhost:5600/memory"


def test_host_ipv6_litteral():
    """L'hôte IPv6 entre crochets est conservé, le :port retiré."""
    assert urls_ui.url_brique("GATEWAY", "https", "[::1]:5100") == \
        "https://[::1]:4001/ui"


def test_host_vide_repli_localhost():
    assert urls_ui.url_brique("MAIL", "http", "") == "http://localhost:6030/"


def test_surcharge_env_prime(monkeypatch):
    """Une surcharge `<NOM>_UI_URL` (déploiement / SSO) court-circuite la construction."""
    monkeypatch.setenv("STUDIO_UI_URL", "https://studio.exemple.test/atelier")
    assert urls_ui.url_brique("STUDIO", "http", "192.168.1.89:5100") == \
        "https://studio.exemple.test/atelier"


def test_surcharge_dev_ide_garde_son_nom_historique(monkeypatch):
    """L'IDE dev lit `DEV_IDE_URL` (et non `DEV_IDE_UI_URL`)."""
    monkeypatch.setenv("DEV_IDE_URL", "https://ide.exemple.test/")
    assert urls_ui.url_brique("DEV_IDE", "http", "192.168.1.89:5100") == \
        "https://ide.exemple.test/"


def test_sans_surcharge_pas_de_fuite_env(monkeypatch):
    """Sans env posé, on construit bien relativement (pas de résidu d'un autre test)."""
    monkeypatch.delenv("STUDIO_UI_URL", raising=False)
    assert urls_ui.url_brique("STUDIO", "https", "100.124.248.226") == \
        "https://100.124.248.226:6060/atelier"
