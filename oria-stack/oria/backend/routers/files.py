import os

from fastapi import APIRouter, Depends, UploadFile, File as FastAPIFile, HTTPException
from fastapi.responses import FileResponse

from routers.auth import get_current_user
from services.files_service import FilesService, get_files_service

router = APIRouter()


def _file_dict(f):
    return {
        "id": f.id, "nom": f.nom, "taille": f.taille, "type_mime": f.type_mime,
        "uploader_nom": f.uploader_nom, "uploaded_by": f.uploaded_by,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@router.post("/upload/{room_id}")
async def upload_file(
    room_id: str,
    file: UploadFile = FastAPIFile(...),
    svc: FilesService = Depends(get_files_service),
    user=Depends(get_current_user),
):
    db_file = svc.save_upload(
        upload=file, uploaded_by=user["id"], uploader_nom=user["nom"],
        room_id=room_id,
    )
    return {**_file_dict(db_file), "room_id": room_id}


@router.get("/room/{room_id}")
def lister_fichiers(room_id: str, svc: FilesService = Depends(get_files_service)):
    return [_file_dict(f) for f in svc.list_by_room(room_id)]


@router.get("/download/{file_id}")
def telecharger(file_id: str, svc: FilesService = Depends(get_files_service)):
    f = svc.get_file(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path = svc.absolute_path(f)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Fichier manquant")
    return FileResponse(path, filename=f.nom, media_type=f.type_mime)


@router.post("/upload/building/{building_id}")
async def upload_building(
    building_id: str,
    file: UploadFile = FastAPIFile(...),
    svc: FilesService = Depends(get_files_service),
    user=Depends(get_current_user),
):
    db_file = svc.save_upload(
        upload=file, uploaded_by=user["id"], uploader_nom=user["nom"],
        building_id=building_id,
    )
    return {**_file_dict(db_file), "building_id": building_id}


@router.get("/building/{building_id}")
def lister_building(building_id: str, svc: FilesService = Depends(get_files_service)):
    return [_file_dict(f) for f in svc.list_by_building(building_id)]


@router.post("/upload/world/{world_id}")
async def upload_world(
    world_id: str,
    file: UploadFile = FastAPIFile(...),
    svc: FilesService = Depends(get_files_service),
    user=Depends(get_current_user),
):
    db_file = svc.save_upload(
        upload=file, uploaded_by=user["id"], uploader_nom=user["nom"],
        world_id=world_id,
    )
    return {**_file_dict(db_file), "world_id": world_id}


@router.get("/world/{world_id}")
def lister_world(world_id: str, svc: FilesService = Depends(get_files_service)):
    return [_file_dict(f) for f in svc.list_by_world(world_id)]


@router.delete("/{file_id}")
def supprimer_fichier(
    file_id: str,
    svc: FilesService = Depends(get_files_service),
    user=Depends(get_current_user),
):
    f = svc.get_file(file_id)
    if f:
        svc.delete_file(f)
    return {"status": "ok"}
