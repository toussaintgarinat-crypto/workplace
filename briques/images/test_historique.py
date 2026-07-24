"""Tests — historique des images RÉELLEMENT produites (JSONL borné, best-effort)."""
import historique as H


def _reset():
    H._chemin().unlink(missing_ok=True)


def test_consigner_et_chercher():
    _reset()
    H.consigner(type_="generer", prompt="un chat qui dort", url="/fichiers/a.png", backend="fal")
    H.consigner(type_="generer", prompt="une forêt de cristal", url="/fichiers/b.png", backend="fal")
    trouvees = H.chercher()
    assert [t["url"] for t in trouvees] == ["/fichiers/b.png", "/fichiers/a.png"]  # + récent d'abord


def test_chercher_filtre_par_mot_cle_insensible_a_la_casse():
    _reset()
    H.consigner(type_="generer", prompt="un CHAT qui dort", url="/fichiers/a.png", backend="fal")
    H.consigner(type_="generer", prompt="une forêt", url="/fichiers/b.png", backend="fal")
    trouvees = H.chercher(q="chat")
    assert [t["url"] for t in trouvees] == ["/fichiers/a.png"]


def test_chercher_sans_correspondance_renvoie_vide():
    _reset()
    H.consigner(type_="generer", prompt="un chat", url="/fichiers/a.png", backend="fal")
    assert H.chercher(q="dinosaure") == []


def test_consigner_ignore_url_vide():
    _reset()
    H.consigner(type_="generer", prompt="x", url=None, backend="fal")
    H.consigner(type_="generer", prompt="x", url="", backend="fal")
    assert H.chercher() == []


def test_chercher_respecte_la_limite():
    _reset()
    for i in range(10):
        H.consigner(type_="generer", prompt=f"image {i}", url=f"/fichiers/{i}.png", backend="fal")
    assert len(H.chercher(limite=3)) == 3


def test_bornage_taille(monkeypatch):
    _reset()
    monkeypatch.setenv("IMAGES_HISTORIQUE_MAX", "50")
    for i in range(120):
        H.consigner(type_="generer", prompt=f"image {i}", url=f"/fichiers/{i}.png", backend="fal")
    lignes = H._lignes()
    assert len(lignes) <= 60          # borné à ~50 (réécrit au-delà de 1,2×)
    assert lignes[-1]["url"] == "/fichiers/119.png"    # on garde les plus récentes
