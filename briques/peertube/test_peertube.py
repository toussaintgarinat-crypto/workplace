import pytest
import respx
import httpx
from peertube_client import PeerTubeClient

PEERTUBE_URL = "http://peertube-test:9000"

@pytest.fixture
def client():
    return PeerTubeClient(PEERTUBE_URL, "root", "motdepasse")

@respx.mock
@pytest.mark.asyncio
async def test_lister_videos(client):
    respx.get(f"{PEERTUBE_URL}/api/v1/oauth-clients/local").mock(return_value=httpx.Response(
        200, json={"client_id": "client-id-xxx", "client_secret": "client-secret-xxx"}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.get(f"{PEERTUBE_URL}/api/v1/videos").mock(return_value=httpx.Response(
        200, json={"total": 1, "data": [{"uuid": "abc-123", "name": "Test", "description": "desc",
                                          "thumbnailPath": "/thumb.jpg", "duration": 60, "views": 5}]}
    ))
    videos = await client.lister_videos()
    assert len(videos) == 1
    assert videos[0]["uuid"] == "abc-123"

@respx.mock
@pytest.mark.asyncio
async def test_lister_videos_reessaie_une_fois_si_jeton_expire(client):
    """Même filet que briques/memoire/forge/oria (bug constaté 2026-07-23) : un 401 sur
    le jeton mémoïsé déclenche une invalidation + un seul réessai avec un jeton frais."""
    respx.get(f"{PEERTUBE_URL}/api/v1/oauth-clients/local").mock(return_value=httpx.Response(
        200, json={"client_id": "client-id-xxx", "client_secret": "client-secret-xxx"}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    route = respx.get(f"{PEERTUBE_URL}/api/v1/videos").mock(side_effect=[
        httpx.Response(401, json={"error": "invalid_token"}),
        httpx.Response(200, json={"total": 1, "data": [{"uuid": "abc-123"}]}),
    ])
    videos = await client.lister_videos()
    assert len(videos) == 1
    assert videos[0]["uuid"] == "abc-123"
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_lister_videos_abandonne_si_le_jeton_frais_echoue_aussi(client):
    """Un seul essai de plus (pas de boucle infinie) : si le second essai échoue aussi,
    l'erreur remonte normalement."""
    respx.get(f"{PEERTUBE_URL}/api/v1/oauth-clients/local").mock(return_value=httpx.Response(
        200, json={"client_id": "client-id-xxx", "client_secret": "client-secret-xxx"}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    route = respx.get(f"{PEERTUBE_URL}/api/v1/videos").mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.lister_videos()
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_info_video(client):
    respx.get(f"{PEERTUBE_URL}/api/v1/oauth-clients/local").mock(return_value=httpx.Response(
        200, json={"client_id": "client-id-xxx", "client_secret": "client-secret-xxx"}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.get(f"{PEERTUBE_URL}/api/v1/videos/abc-123").mock(return_value=httpx.Response(
        200, json={"uuid": "abc-123", "name": "Test", "description": "desc",
                   "embedPath": "/videos/embed/abc-123"}
    ))
    info = await client.info_video("abc-123")
    assert info["embedPath"] == "/videos/embed/abc-123"

@respx.mock
@pytest.mark.asyncio
async def test_uploader_video(client):
    respx.get(f"{PEERTUBE_URL}/api/v1/oauth-clients/local").mock(return_value=httpx.Response(
        200, json={"client_id": "client-id-xxx", "client_secret": "client-secret-xxx"}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/videos/upload").mock(return_value=httpx.Response(
        200, json={"video": {"uuid": "new-uuid", "name": "Ma vidéo",
                              "url": "http://192.168.1.89:9000/videos/watch/new-uuid"}}
    ))
    result = await client.uploader_video("Ma vidéo", "desc", b"bytes_video", "video.mp4")
    assert result["uuid"] == "new-uuid"

@respx.mock
@pytest.mark.asyncio
async def test_creer_live(client):
    respx.get(f"{PEERTUBE_URL}/api/v1/oauth-clients/local").mock(return_value=httpx.Response(
        200, json={"client_id": "client-id-xxx", "client_secret": "client-secret-xxx"}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/users/token").mock(return_value=httpx.Response(
        200, json={"access_token": "tok123", "token_type": "Bearer", "expires_in": 86400}
    ))
    respx.post(f"{PEERTUBE_URL}/api/v1/videos/live").mock(return_value=httpx.Response(
        200, json={"video": {"uuid": "live-uuid"}}
    ))
    respx.get(f"{PEERTUBE_URL}/api/v1/videos/live/live-uuid").mock(return_value=httpx.Response(
        200, json={"rtmpUrl": "rtmp://192.168.1.89:1935/live", "streamKey": "key123"}
    ))
    live = await client.creer_live("Mon live", "Session de travail")
    assert live["rtmpUrl"] == "rtmp://192.168.1.89:1935/live"
    assert live["streamKey"] == "key123"


# === Tests API FastAPI ===
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import io


def test_sante_ok():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.get("/sante")
        assert resp.status_code == 200
        assert resp.json()["statut"] == "ok"


def test_lister_videos_vide():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.get("/videos")
        assert resp.status_code == 200
        assert resp.json() == []


def test_lister_videos_avec_resultats():
    from main import app
    video = {"uuid": "abc", "name": "Test", "description": "d",
             "thumbnailPath": "/thumb.jpg", "duration": 60, "views": 3,
             "embedPath": "/videos/embed/abc"}
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[video])
        client = TestClient(app)
        resp = client.get("/videos")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["uuid"] == "abc"
        assert "embedUrl" in data[0]


def test_rechercher_videos():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.lister_videos = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.post("/videos/rechercher", json={"query": "test"})
        assert resp.status_code == 200
        mock_pt.lister_videos.assert_called_once_with(search="test")


def test_upload_video():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.uploader_video = AsyncMock(
            return_value={"uuid": "new-u", "url": "http://x/watch/new-u"}
        )
        client = TestClient(app)
        fichier = io.BytesIO(b"fake_video_bytes")
        resp = client.post("/videos/upload", data={"nom": "Ma vidéo", "description": "test"},
                           files={"fichier": ("video.mp4", fichier, "video/mp4")})
        assert resp.status_code == 200
        assert resp.json()["uuid"] == "new-u"


def test_upload_video_refuse_un_fichier_malveillant():
    from main import app
    import main as m
    with patch("main._peertube") as mock_pt, \
         patch.object(m, "AUDIT_FICHIERS_URL", "http://audit-test:6170"), \
         respx.mock:
        respx.post("http://audit-test:6170/scanner").mock(
            return_value=httpx.Response(200, json={"ok": True, "propre": False,
                                                    "raison": "Eicar-Test-Signature",
                                                    "scanner": "clamav"}))
        client = TestClient(app)
        resp = client.post("/videos/upload", data={"nom": "Vidéo", "description": ""},
                           files={"fichier": ("v.mp4", io.BytesIO(b"faux virus"), "video/mp4")})
        assert resp.status_code == 400
        mock_pt.uploader_video.assert_not_called()


def test_upload_video_refuse_par_precaution_si_antivirus_injoignable():
    from main import app
    import main as m
    with patch("main._peertube") as mock_pt, \
         patch.object(m, "AUDIT_FICHIERS_URL", "http://audit-test:6170"), \
         respx.mock:
        respx.post("http://audit-test:6170/scanner").mock(side_effect=httpx.ConnectError("refus"))
        client = TestClient(app)
        resp = client.post("/videos/upload", data={"nom": "Vidéo", "description": ""},
                           files={"fichier": ("v.mp4", io.BytesIO(b"contenu"), "video/mp4")})
        assert resp.status_code == 503
        mock_pt.uploader_video.assert_not_called()


def test_creer_live_api():
    from main import app
    with patch("main._peertube") as mock_pt:
        mock_pt.creer_live = AsyncMock(
            return_value={"uuid": "live-1", "rtmpUrl": "rtmp://192.168.1.89:1935/live", "streamKey": "sk"}
        )
        client = TestClient(app)
        resp = client.post("/live", json={"nom": "Session", "description": "live"})
        assert resp.status_code == 200
        assert resp.json()["rtmpUrl"] == "rtmp://192.168.1.89:1935/live"
