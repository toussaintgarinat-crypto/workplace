from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from models.shared_zone import SharedZone, ZoneRole, ZoneScope
from routers.auth import get_current_user
from services.shared_zones_service import SharedZonesService, get_shared_zones_service

router = APIRouter()


class CreateZoneBody(BaseModel):
    name:                str
    scope:               ZoneScope = ZoneScope.user
    world_id:            Optional[str] = None
    mempalace_namespace: Optional[str] = None


class InviteMemberBody(BaseModel):
    user_id: str
    role:    ZoneRole = ZoneRole.reader


def _zone_dict(zone: SharedZone) -> dict:
    return {
        "id":                  zone.id,
        "name":                zone.name,
        "owner_id":            zone.owner_id,
        "scope":               zone.scope,
        "world_id":            zone.world_id,
        "mempalace_namespace": zone.mempalace_namespace,
        "created_at":          zone.created_at.isoformat(),
    }


@router.post("/", status_code=201)
def create_zone(
    body: CreateZoneBody,
    svc: SharedZonesService = Depends(get_shared_zones_service),
    current_user=Depends(get_current_user),
):
    zone = svc.create_zone(
        name=body.name, owner_id=current_user["id"],
        scope=body.scope, world_id=body.world_id,
        mempalace_namespace=body.mempalace_namespace,
    )
    return _zone_dict(zone)


@router.get("/")
def list_zones(
    svc: SharedZonesService = Depends(get_shared_zones_service),
    current_user=Depends(get_current_user),
):
    memberships = svc.list_user_memberships(current_user["id"])
    zone_ids = [m.zone_id for m in memberships]
    zones = svc.list_zones_by_ids(zone_ids)
    return [_zone_dict(z) for z in zones]


@router.get("/{zone_id}")
def get_zone(
    zone_id: str,
    svc: SharedZonesService = Depends(get_shared_zones_service),
    current_user=Depends(get_current_user),
):
    zone = svc.require_access(zone_id, current_user["id"])
    return _zone_dict(zone)


@router.delete("/{zone_id}", status_code=204)
def delete_zone(
    zone_id: str,
    svc: SharedZonesService = Depends(get_shared_zones_service),
    current_user=Depends(get_current_user),
):
    zone = svc.get_zone(zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    if zone.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Only the owner can delete a zone")
    svc.delete_zone(zone)


@router.post("/{zone_id}/members", status_code=201)
def invite_member(
    zone_id: str,
    body: InviteMemberBody,
    svc: SharedZonesService = Depends(get_shared_zones_service),
    current_user=Depends(get_current_user),
):
    zone = svc.get_zone(zone_id)
    if not zone or zone.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Only the owner can invite members")
    if body.role == ZoneRole.owner:
        raise HTTPException(status_code=400, detail="Cannot assign owner role via invitation")
    svc.upsert_member(zone_id, body.user_id, body.role)
    return {"ok": True}


@router.delete("/{zone_id}/members/{user_id}", status_code=204)
def remove_member(
    zone_id: str,
    user_id: str,
    svc: SharedZonesService = Depends(get_shared_zones_service),
    current_user=Depends(get_current_user),
):
    zone = svc.get_zone(zone_id)
    if not zone or zone.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Only the owner can remove members")
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot remove yourself as owner")
    svc.remove_member(zone_id, user_id)


@router.get("/{zone_id}/members")
def list_members(
    zone_id: str,
    svc: SharedZonesService = Depends(get_shared_zones_service),
    current_user=Depends(get_current_user),
):
    svc.require_access(zone_id, current_user["id"])
    members = svc.list_members(zone_id)
    return [
        {"user_id": m.user_id, "role": m.role, "joined_at": m.joined_at.isoformat()}
        for m in members
    ]
