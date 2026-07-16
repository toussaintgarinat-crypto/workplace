"""CRUD listes de courses/tâches + membres + invitations — /lists."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.orm import (
    ShoppingItem,
    ShoppingList,
    ShoppingListInvitation,
    ShoppingListMember,
    UserProfile,
)
from models.schemas import (
    ListInvitationCreate,
    ListMemberOut,
    ShoppingListCreate,
    ShoppingListOut,
    ShoppingListUpdate,
    ShoppingListWithMetaOut,
)
from utils.access import require_list_access

router = APIRouter(prefix="/lists", tags=["lists"])


def _with_meta(liste: ShoppingList, role: str, nb: int) -> ShoppingListWithMetaOut:
    return ShoppingListWithMetaOut(
        **ShoppingListOut.model_validate(liste).model_dump(), role=role, nb_a_prendre=nb)


async def _nb_a_prendre(db: AsyncSession, list_id: str) -> int:
    nb = await db.scalar(
        select(func.count()).select_from(ShoppingItem).where(
            ShoppingItem.list_id == list_id, ShoppingItem.checked.is_(False)))
    return nb or 0


@router.get("", response_model=list[ShoppingListWithMetaOut])
async def list_lists(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    uid = user["sub"]
    owned = (await db.execute(select(ShoppingList).where(ShoppingList.created_by == uid))).scalars().all()
    owned_ids = {l.id for l in owned}
    member_rows = (await db.execute(
        select(ShoppingListMember, ShoppingList)
        .join(ShoppingList, ShoppingListMember.list_id == ShoppingList.id)
        .where(ShoppingListMember.user_id == uid)
    )).all()
    vues: list[tuple[ShoppingList, str]] = [(l, "owner") for l in owned]
    for member, liste in member_rows:
        if liste.id not in owned_ids:
            vues.append((liste, member.role))
    resultat: list[ShoppingListWithMetaOut] = []
    for liste, role in vues:
        resultat.append(_with_meta(liste, role, await _nb_a_prendre(db, liste.id)))
    return resultat


@router.post("", response_model=ShoppingListWithMetaOut, status_code=status.HTTP_201_CREATED)
async def create_list(body: ShoppingListCreate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    kind = body.kind if body.kind in ("courses", "taches") else "courses"
    liste = ShoppingList(name=body.name, kind=kind, created_by=user["sub"])
    db.add(liste)
    await db.commit()
    await db.refresh(liste)
    return _with_meta(liste, "owner", 0)


@router.get("/{list_id}", response_model=ShoppingListWithMetaOut)
async def get_list(list_id: str, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(get_current_user)):
    liste, role = await require_list_access(db, list_id, user["sub"], min_role="viewer")
    return _with_meta(liste, role, await _nb_a_prendre(db, list_id))


@router.patch("/{list_id}", response_model=ShoppingListWithMetaOut)
async def update_list(list_id: str, body: ShoppingListUpdate, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    liste, role = await require_list_access(db, list_id, user["sub"], min_role="editor")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(liste, k, v)
    await db.commit()
    await db.refresh(liste)
    return _with_meta(liste, role, await _nb_a_prendre(db, list_id))


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(list_id: str, db: AsyncSession = Depends(get_db),
                      user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="owner")
    await db.delete(liste)
    await db.commit()


@router.get("/{list_id}/members", response_model=list[ListMemberOut])
async def list_members(list_id: str, db: AsyncSession = Depends(get_db),
                       user: dict = Depends(get_current_user)):
    liste, _ = await require_list_access(db, list_id, user["sub"], min_role="viewer")
    membres = (await db.execute(
        select(ShoppingListMember).where(ShoppingListMember.list_id == list_id))).scalars().all()

    async def _ligne(uid: str, role: str) -> ListMemberOut:
        prof = await db.get(UserProfile, uid)
        return ListMemberOut(
            user_id=uid, role=role,
            display_name=prof.display_name if prof else None,
            avatar_color=prof.avatar_color if prof else None)

    sortie: list[ListMemberOut] = []
    uids_membres = {m.user_id for m in membres}
    if liste.created_by not in uids_membres:
        sortie.append(await _ligne(liste.created_by, "owner"))
    for m in membres:
        sortie.append(await _ligne(m.user_id, m.role))
    return sortie


@router.post("/{list_id}/invitations", status_code=status.HTTP_201_CREATED)
async def invite_to_list(list_id: str, body: ListInvitationCreate, db: AsyncSession = Depends(get_db),
                         user: dict = Depends(get_current_user)):
    await require_list_access(db, list_id, user["sub"], min_role="editor")
    role = body.role if body.role in ("viewer", "editor") else "viewer"
    inv = ShoppingListInvitation(
        list_id=list_id, role=role, email=body.email, created_by=user["sub"],
        expires_at=datetime.utcnow() + timedelta(hours=body.expire_heures))
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return {"token": inv.token, "role": inv.role, "expires_at": inv.expires_at.isoformat()}


@router.post("/invitations/{token}/accept", status_code=status.HTTP_200_OK)
async def accept_list_invitation(token: str, db: AsyncSession = Depends(get_db),
                                 user: dict = Depends(get_current_user)):
    inv = (await db.execute(
        select(ShoppingListInvitation).where(ShoppingListInvitation.token == token))).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation introuvable")
    if inv.used_at is not None or (inv.expires_at and inv.expires_at < datetime.utcnow()):
        raise HTTPException(status_code=410, detail="Invitation expirée ou déjà utilisée")
    uid = user["sub"]
    existe = (await db.execute(select(ShoppingListMember).where(
        ShoppingListMember.list_id == inv.list_id, ShoppingListMember.user_id == uid))).scalar_one_or_none()
    if existe is None:
        db.add(ShoppingListMember(list_id=inv.list_id, user_id=uid, role=inv.role))
    inv.used_at = datetime.utcnow()
    await db.commit()
    return {"list_id": inv.list_id, "role": inv.role}
