"""
Service Coins — accès DB pour le router coins_router (Sprint 100).

Toute la logique de requêtes SQLAlchemy autour des Coins/Dossiers/Fichiers
et des accès payants aux rooms est encapsulée ici. Le router n'utilise plus
`db.query()` directement.
"""

from __future__ import annotations

import os
import shutil
import uuid
from typing import Optional

from fastapi import Depends, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models.building import Room
from models.coin import Coin, CoinDossier, CoinFichier, RoomAccesPaye


class CoinsService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Rooms / accès payant ─────────────────────────────────────────────
    def get_room(self, room_id: str) -> Optional[Room]:
        return self.db.query(Room).filter(Room.id == room_id).first()

    def get_acces(self, room_id: str, user_id: str) -> Optional[RoomAccesPaye]:
        return self.db.query(RoomAccesPaye).filter(
            RoomAccesPaye.room_id == room_id,
            RoomAccesPaye.user_id == user_id,
            RoomAccesPaye.actif == True,
        ).first()

    def has_access(self, room_id: str, user_id: str) -> bool:
        room = self.get_room(room_id)
        if not room or not room.est_payante:
            return True
        return self.get_acces(room_id, user_id) is not None

    def get_acces_any_state(self, room_id: str, user_id: str) -> Optional[RoomAccesPaye]:
        """Récupère un accès existant quel que soit son état (pour les webhooks)."""
        return self.db.query(RoomAccesPaye).filter(
            RoomAccesPaye.room_id == room_id,
            RoomAccesPaye.user_id == user_id,
        ).first()

    def get_acces_by_subscription(self, subscription_id: str) -> Optional[RoomAccesPaye]:
        return self.db.query(RoomAccesPaye).filter(
            RoomAccesPaye.stripe_subscription_id == subscription_id
        ).first()

    def upsert_acces_completion(
        self, room_id: str, user_id: str, ptype: str,
        session_id: str, subscription_id: Optional[str],
    ) -> RoomAccesPaye:
        existe = self.get_acces_any_state(room_id, user_id)
        if existe:
            existe.actif = True
            existe.stripe_subscription_id = subscription_id
            self.db.commit()
            return existe
        acces = RoomAccesPaye(
            room_id=room_id, user_id=user_id,
            type_paiement=ptype,
            stripe_session_id=session_id,
            stripe_subscription_id=subscription_id,
            actif=True,
        )
        self.db.add(acces)
        self.db.commit()
        return acces

    def desactiver_acces_par_subscription(self, subscription_id: str) -> None:
        acces = self.get_acces_by_subscription(subscription_id)
        if acces:
            acces.actif = False
            self.db.commit()

    # ─── Coins ────────────────────────────────────────────────────────────
    def list_coins(self, room_id: str) -> list[Coin]:
        return self.db.query(Coin).filter(Coin.room_id == room_id).all()

    def get_coin_for_user(self, room_id: str, user_id: str) -> Optional[Coin]:
        return self.db.query(Coin).filter(
            Coin.room_id == room_id, Coin.user_id == user_id
        ).first()

    def get_coin_by_id(self, coin_id: str) -> Optional[Coin]:
        return self.db.query(Coin).filter(Coin.id == coin_id).first()

    def get_owned_coin(self, coin_id: str, user_id: str) -> Optional[Coin]:
        return self.db.query(Coin).filter(
            Coin.id == coin_id, Coin.user_id == user_id
        ).first()

    def create_coin(
        self, room_id: str, user_id: str, user_nom: str,
        user_emoji: str, titre: str, description: str,
    ) -> Coin:
        coin = Coin(
            room_id=room_id, user_id=user_id,
            user_nom=user_nom, user_emoji=user_emoji,
            titre=titre, description=description,
        )
        self.db.add(coin)
        self.db.commit()
        self.db.refresh(coin)
        return coin

    def get_user_avatar_emoji(self, user_id: str) -> str:
        from models.user import User as UserModel
        u = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return u.avatar_emoji if u else "👤"

    def update_coin(self, coin: Coin, titre: str = "", description: str = "") -> Coin:
        if titre:
            coin.titre = titre
        if description:
            coin.description = description
        self.db.commit()
        self.db.refresh(coin)
        return coin

    def delete_coin(self, coin: Coin) -> None:
        self.db.delete(coin)
        self.db.commit()

    # ─── Dossiers ─────────────────────────────────────────────────────────
    def list_dossiers(self, coin_id: str) -> list[CoinDossier]:
        return self.db.query(CoinDossier).filter(
            CoinDossier.coin_id == coin_id
        ).all()

    def get_dossier(self, coin_id: str, dossier_id: str) -> Optional[CoinDossier]:
        return self.db.query(CoinDossier).filter(
            CoinDossier.id == dossier_id, CoinDossier.coin_id == coin_id
        ).first()

    def get_dossier_by_id(self, dossier_id: str) -> Optional[CoinDossier]:
        return self.db.query(CoinDossier).filter(
            CoinDossier.id == dossier_id
        ).first()

    def create_dossier(
        self, coin_id: str, nom: str, visibilite: str, parent_id: Optional[str],
    ) -> CoinDossier:
        d = CoinDossier(
            coin_id=coin_id, nom=nom,
            visibilite=visibilite, parent_id=parent_id,
        )
        self.db.add(d)
        self.db.commit()
        self.db.refresh(d)
        return d

    def update_dossier(self, dossier: CoinDossier, nom: str = "", visibilite: str = "") -> CoinDossier:
        if nom:
            dossier.nom = nom
        if visibilite:
            dossier.visibilite = visibilite
        self.db.commit()
        self.db.refresh(dossier)
        return dossier

    def delete_dossier(self, dossier: CoinDossier) -> None:
        self.db.delete(dossier)
        self.db.commit()

    # ─── Fichiers ─────────────────────────────────────────────────────────
    def get_fichier(self, fichier_id: str) -> Optional[CoinFichier]:
        return self.db.query(CoinFichier).filter(
            CoinFichier.id == fichier_id
        ).first()

    def get_fichier_in_dossier(self, fichier_id: str, dossier_id: str) -> Optional[CoinFichier]:
        return self.db.query(CoinFichier).filter(
            CoinFichier.id == fichier_id, CoinFichier.dossier_id == dossier_id
        ).first()

    def save_uploaded_file(
        self, coin_id: str, dossier_id: str, user_id: str,
        file: UploadFile, upload_dir: str,
    ) -> CoinFichier:
        ext = os.path.splitext(file.filename or "")[1]
        file_id = str(uuid.uuid4())
        filename = f"coin_{file_id}{ext}"
        path = os.path.join(upload_dir, filename)
        with open(path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        size = os.path.getsize(path)

        db_file = CoinFichier(
            id=file_id, dossier_id=dossier_id, coin_id=coin_id,
            nom=file.filename or filename,
            path=filename, taille=size,
            type_mime=file.content_type or "application/octet-stream",
            uploaded_by=user_id,
        )
        self.db.add(db_file)
        self.db.commit()
        self.db.refresh(db_file)
        return db_file

    def delete_fichier(self, fichier: CoinFichier, upload_dir: str) -> None:
        p = os.path.join(upload_dir, fichier.path)
        if os.path.exists(p):
            os.remove(p)
        self.db.delete(fichier)
        self.db.commit()


def get_coins_service(db: Session = Depends(get_db)) -> CoinsService:
    """Dépendance FastAPI."""
    return CoinsService(db)
