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
async def test_info_video(client):
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
