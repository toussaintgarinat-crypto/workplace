"""Service Social — accès DB pour social_router (Sprint 100)."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.social import Notification, UserFollow
from models.user import User
from models.world import World


class SocialService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Follow ──────────────────────────────────────────────────────
    def get_follow(self, follower_id: str, followed_id: str) -> Optional[UserFollow]:
        return self.db.query(UserFollow).filter_by(
            follower_id=follower_id, followed_id=followed_id,
        ).first()

    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter_by(id=user_id).first()

    def create_follow(self, follower_id: str, followed_id: str) -> UserFollow:
        f = UserFollow(follower_id=follower_id, followed_id=followed_id)
        self.db.add(f)
        # commit deferred — caller peut enchaîner avec une Notification
        return f

    def delete_follow(self, follow: UserFollow) -> None:
        self.db.delete(follow)
        self.db.commit()

    def list_following(self, user_id: str) -> list[User]:
        follows = self.db.query(UserFollow).filter_by(follower_id=user_id).all()
        ids = [f.followed_id for f in follows]
        if not ids:
            return []
        return self.db.query(User).filter(User.id.in_(ids)).all()

    def list_followers(self, user_id: str) -> list[User]:
        follows = self.db.query(UserFollow).filter_by(followed_id=user_id).all()
        ids = [f.follower_id for f in follows]
        if not ids:
            return []
        return self.db.query(User).filter(User.id.in_(ids)).all()

    def list_followed_ids(self, user_id: str) -> list[str]:
        return [
            f.followed_id
            for f in self.db.query(UserFollow).filter_by(follower_id=user_id).all()
        ]

    # ─── Feed ────────────────────────────────────────────────────────
    def list_public_worlds_by_owners(self, owner_ids: list[str], limit: int = 30) -> list[World]:
        if not owner_ids:
            return []
        return (
            self.db.query(World)
            .filter(
                World.owner_id.in_(owner_ids),
                World.is_public == True,
                World.is_garden == False,
            )
            .order_by(World.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_users_map(self, user_ids: list[str]) -> dict[str, User]:
        if not user_ids:
            return {}
        return {u.id: u for u in self.db.query(User).filter(User.id.in_(user_ids)).all()}

    # ─── Notifications ───────────────────────────────────────────────
    def add_notification(self, user_id: str, type_: str, data_dict: dict) -> Notification:
        n = Notification(user_id=user_id, type=type_, data=json.dumps(data_dict))
        self.db.add(n)
        # commit deferred
        return n

    def commit(self) -> None:
        self.db.commit()

    def list_notifs(self, user_id: str, limit: int = 50) -> list[Notification]:
        return (
            self.db.query(Notification)
            .filter_by(user_id=user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .all()
        )

    def count_unread_notifs(self, user_id: str) -> int:
        return self.db.query(Notification).filter_by(user_id=user_id, read=False).count()

    def get_notif(self, notif_id: str, user_id: str) -> Optional[Notification]:
        return self.db.query(Notification).filter_by(
            id=notif_id, user_id=user_id,
        ).first()

    def mark_notif_read(self, notif: Notification) -> None:
        notif.read = True
        self.db.commit()

    def mark_all_notifs_read(self, user_id: str) -> None:
        self.db.query(Notification).filter_by(
            user_id=user_id, read=False,
        ).update({"read": True})
        self.db.commit()

    # ─── Public profile ──────────────────────────────────────────────
    def get_user_public_worlds(self, user_id: str, limit: int = 20) -> list[World]:
        return (
            self.db.query(World)
            .filter_by(owner_id=user_id, is_public=True, is_garden=False)
            .order_by(World.created_at.desc())
            .limit(limit)
            .all()
        )


def get_social_service(db: Session = Depends(get_db)) -> SocialService:
    return SocialService(db)
