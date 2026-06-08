"""Service Auth — accès DB pour auth router (Sprint 100)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from config import config
from database import get_db
from models.user import User


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def get_user(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def relink_user_id(self, user: User, new_id: str) -> User:
        user.id = new_id
        self.db.commit()
        return user

    def list_membres_for_user(self, user_id: str):
        from models.world import Member
        return self.db.query(Member).filter(Member.user_id == user_id).all()

    def delete_membres_for_user(self, user_id: str) -> None:
        from models.world import Member
        self.db.query(Member).filter(Member.user_id == user_id).delete()
        self.db.commit()

    def commit(self) -> None:
        self.db.commit()

    def add(self, instance) -> None:
        self.db.add(instance)

    def flush(self) -> None:
        self.db.flush()

    def provision_new_user(
        self, keycloak_sub: str, payload: dict,
        matrix_module,
    ) -> User:
        """Crée un utilisateur Oria au premier login Keycloak et provisionne ses ressources."""
        nom = (payload.get("nom") or payload.get("preferred_username")
               or payload.get("name") or "Utilisateur")
        email = payload.get("email") or f"{keycloak_sub}@oria.local"
        avatar_emoji = payload.get("avatarEmoji") or "👤"

        # Liaison sur l'email si un compte local existait avant la migration Keycloak
        existing = self.get_user_by_email(email)
        if existing:
            if existing.id != keycloak_sub:
                self.relink_user_id(existing, keycloak_sub)
            return existing

        user = User(
            id=keycloak_sub,
            email=email,
            nom=nom,
            avatar_emoji=avatar_emoji,
            hashed_password="",
        )
        self.add(user)
        self.flush()

        # Matrix provisioning (dégradé si Synapse indisponible)
        matrix_data = matrix_module.provision_user(user.id)
        if matrix_data:
            user.matrix_user_id      = matrix_data["user_id"]
            user.matrix_access_token = matrix_data["access_token"]
            user.matrix_provisioned  = "true"

        # Jardin Secret inviolable
        from models.world import World, Member
        from models.building import Building, Room

        jardin = World(
            id=str(uuid.uuid4()),
            nom="Mon Jardin Secret",
            description="Mon espace privé, invisible pour tous",
            emoji="🌿",
            couleur="#2d5a27",
            owner_id=user.id,
            is_public=False,
            is_garden=True,
        )
        self.add(jardin)
        self.add(Member(world_id=jardin.id, user_id=user.id, nom=user.nom,
                        avatar_emoji=user.avatar_emoji, role="proprietaire"))
        self.flush()

        bld = Building(id=str(uuid.uuid4()), world_id=jardin.id,
                       nom="Mon espace", type="maison", emoji="🌿", couleur="#2d5a27")
        self.add(bld)
        self.flush()
        for pos, (nom_room, emoji) in enumerate([
            ("📔 Journal", "📔"), ("💭 Pensées", "💭"), ("🎯 Objectifs", "🎯"),
        ]):
            self.add(Room(id=str(uuid.uuid4()), building_id=bld.id,
                          nom=nom_room, type="texte", emoji=emoji, position=pos))

        user.jardin_world_id = jardin.id

        # Agent personnel du Jardin
        from models.agent import AgentDefinition as _AgentDef
        self.add(_AgentDef(
            id=str(uuid.uuid4()),
            world_id=jardin.id,
            owner_id=user.id,
            nom="Mon Assistant",
            avatar_emoji="🌿",
            description="Ton assistant personnel — il se souvient de tout ce que tu partages.",
            system_prompt=(
                f"Tu es l'assistant personnel de {user.nom}. "
                "Tu as accès à sa mémoire longue durée (documents, notes, conversations passées). "
                "Sois direct, chaleureux et contextuel. Utilise la mémoire pour personnaliser tes réponses."
            ),
            forge_url=config.FORGE_URL,
            forge_provider=config.DEFAULT_AGENT_PROVIDER,
            forge_model=config.DEFAULT_AGENT_MODEL,
            use_memory=True,
            is_active=True,
            is_jardin_agent=True,
        ))
        self.commit()
        return user

    def update_profile(self, user: User, **fields) -> User:
        for k, v in fields.items():
            if v is not None:
                setattr(user, k, v)
        self.db.commit()
        self.db.refresh(user)
        return user

    def mark_setup_completed(self, user: User) -> User:
        user.setup_completed_at = datetime.now(timezone.utc)
        self.db.commit()
        return user

    def reset_setup(self, user: User) -> User:
        user.setup_completed_at = None
        self.db.commit()
        return user

    def anonymize_account(self, user: User) -> None:
        """Suppression RGPD : anonymise l'utilisateur et purge ses memberships."""
        self.delete_membres_for_user(user.id)
        user.email = f"deleted_{user.id}@rgpd.deleted"
        user.nom = "[Compte supprimé]"
        user.avatar_emoji = "❌"
        user.hashed_password = ""
        user.matrix_user_id = None
        user.matrix_access_token = None
        self.db.commit()


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)
