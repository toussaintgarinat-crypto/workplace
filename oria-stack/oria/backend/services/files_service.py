"""Service Files — accès DB pour files router (Sprint 100)."""

from __future__ import annotations

import os
import shutil
import uuid
from typing import Optional

from fastapi import Depends, UploadFile
from sqlalchemy.orm import Session

from config import config as oria_config
from database import get_db
from models.building import File


class FilesService:
    def __init__(self, db: Session):
        self.db = db
        self.upload_dir = oria_config.UPLOAD_DIR

    # ─── Lookup ───────────────────────────────────────────────────────────
    def get_file(self, file_id: str) -> Optional[File]:
        return self.db.query(File).filter(File.id == file_id).first()

    def list_by_room(self, room_id: str) -> list[File]:
        return (
            self.db.query(File)
            .filter(File.room_id == room_id)
            .order_by(File.created_at.desc())
            .all()
        )

    def list_by_building(self, building_id: str) -> list[File]:
        return (
            self.db.query(File)
            .filter(File.building_id == building_id)
            .order_by(File.created_at.desc())
            .all()
        )

    def list_by_world(self, world_id: str) -> list[File]:
        return (
            self.db.query(File)
            .filter(File.world_id == world_id)
            .order_by(File.created_at.desc())
            .all()
        )

    # ─── Upload helper ────────────────────────────────────────────────────
    def save_upload(
        self, upload: UploadFile, uploaded_by: str, uploader_nom: str,
        room_id: Optional[str] = None,
        building_id: Optional[str] = None,
        world_id: Optional[str] = None,
    ) -> File:
        ext = os.path.splitext(upload.filename or "")[1]
        file_id = str(uuid.uuid4())
        filename = f"{file_id}{ext}"
        path = os.path.join(self.upload_dir, filename)
        with open(path, "wb") as out:
            shutil.copyfileobj(upload.file, out)
        size = os.path.getsize(path)

        db_file = File(
            id=file_id,
            room_id=room_id, building_id=building_id, world_id=world_id,
            uploaded_by=uploaded_by, uploader_nom=uploader_nom,
            nom=upload.filename or filename, taille=size,
            type_mime=upload.content_type or "application/octet-stream",
            path=filename,
        )
        self.db.add(db_file)
        self.db.commit()
        self.db.refresh(db_file)
        return db_file

    # ─── Suppression ──────────────────────────────────────────────────────
    def delete_file(self, f: File) -> None:
        p = os.path.join(self.upload_dir, f.path)
        if os.path.exists(p):
            os.remove(p)
        self.db.delete(f)
        self.db.commit()

    def absolute_path(self, f: File) -> str:
        return os.path.join(self.upload_dir, f.path)


def get_files_service(db: Session = Depends(get_db)) -> FilesService:
    return FilesService(db)
