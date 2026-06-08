from fastapi import APIRouter
from pydantic import BaseModel
from jose import jwt
import time

from config import config

router = APIRouter()

class TokenRequest(BaseModel):
    room_id:  str
    user_id:  str
    user_nom: str

@router.post("/")
def generer_token(req: TokenRequest):
    now = int(time.time())
    claims = {
        "iss": config.LIVEKIT_API_KEY, "sub": req.user_id,
        "iat": now, "exp": now + 3600, "name": req.user_nom,
        "video": {"roomJoin": True, "room": req.room_id, "canPublish": True, "canSubscribe": True},
    }
    return {"token": jwt.encode(claims, config.LIVEKIT_API_SECRET, algorithm="HS256")}
