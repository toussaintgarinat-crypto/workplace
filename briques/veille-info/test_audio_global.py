"""Tests du module audio_global (S199) : concaténation ffmpeg de plusieurs digests déjà
audio-générés + interludes TTS par thématique. Aucun appel réseau réel (httpx et
subprocess.run sont mockés) ; ffmpeg/ffprobe RÉELS sont utilisés pour le test bout-en-bout
minimal (disponibles dans l'image, cf. Task 4)."""
import stockage
import audio_global


def test_generer_sans_digest_selectionne_leve():
    try:
        audio_global.generer("audio-vide", [])
        assert False, "devrait lever AudioGlobalError"
    except audio_global.AudioGlobalError as e:
        assert "sélectionné" in str(e)


def test_generer_digest_introuvable_leve():
    try:
        audio_global.generer("audio-intro", [999999])
        assert False, "devrait lever AudioGlobalError"
    except audio_global.AudioGlobalError as e:
        assert "introuvable" in str(e)


def test_generer_digest_sans_audio_leve(monkeypatch):
    d = stockage.inserer_digest("audio-sansaudio", "Résumé.", 1, thematique="Tech")
    try:
        audio_global.generer("audio-sansaudio", [d["id"]])
        assert False, "devrait lever AudioGlobalError"
    except audio_global.AudioGlobalError as e:
        assert "audio" in str(e).lower()


def test_generer_concatene_deux_digests(monkeypatch, tmp_path):
    d1 = stockage.inserer_digest("audio-ok", "Résumé tech.", 1, thematique="Tech")
    d2 = stockage.inserer_digest("audio-ok", "Résumé cosmétique.", 1, thematique="Cosmétique")
    stockage.inserer_audio_digest(d1["id"], "https://voix.example/1.mp3", 5.0)
    stockage.inserer_audio_digest(d2["id"], "https://voix.example/2.mp3", 5.0)

    monkeypatch.setattr(audio_global, "_AUDIO_GLOBAL_DIR", tmp_path)

    # Fabrique un vrai petit MP3 silencieux (1s) réutilisé pour tous les segments (interludes
    # + digests) — évite de dépendre d'un vrai réseau tout en exerçant le VRAI ffmpeg concat.
    import subprocess
    segment = tmp_path / "silence.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                    "-t", "1", "-c:a", "libmp3lame", str(segment)], check=True, capture_output=True)
    octets_segment = segment.read_bytes()

    def _fausse_synthese_interlude(texte):
        return octets_segment
    monkeypatch.setattr(audio_global, "_synthetiser_interlude", _fausse_synthese_interlude)

    def _faux_telecharger(url):
        return octets_segment
    monkeypatch.setattr(audio_global, "_telecharger", _faux_telecharger)

    appels = []
    def _faux_inserer_audio_global(user_id, jeton, ordre_digest_ids, fichier_path, duree, expire_le):
        appels.append((user_id, jeton, ordre_digest_ids, fichier_path, duree, expire_le))
        return {"id": 1, "user_id": user_id, "jeton": jeton, "ordre_thematiques": ordre_digest_ids,
                "fichier_path": fichier_path, "duree_secondes": duree, "expire_le": expire_le}
    # raising=False : `stockage.inserer_audio_global` n'existe pas encore avant Task 6 (cf.
    # note d'ordre d'exécution du brief) — le mock doit tenir même si l'attribut est absent.
    monkeypatch.setattr(stockage, "inserer_audio_global", _faux_inserer_audio_global, raising=False)

    resultat = audio_global.generer("audio-ok", [d1["id"], d2["id"]])

    assert resultat["id"] == 1
    assert len(appels) == 1
    _, jeton, ordre, fichier_path, duree, _ = appels[0]
    assert ordre == [d1["id"], d2["id"]]
    assert Path(fichier_path).exists()
    assert duree is not None and duree > 0


from pathlib import Path  # noqa: E402 — import groupé en bas pour rester lisible dans le diff
