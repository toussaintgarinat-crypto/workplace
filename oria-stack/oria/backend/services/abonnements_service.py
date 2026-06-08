"""Service Abonnements — accès DB pour abonnements router (Sprint 100)."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from models.abonnement import Abonnement, MembreAbonnement
from models.world import Member, World


class AbonnementsService:
    def __init__(self, db: Session):
        self.db = db

    # ─── Worlds / membres helpers ────────────────────────────────────────
    def get_world(self, world_id: str) -> Optional[World]:
        return self.db.query(World).filter(World.id == world_id).first()

    def get_membre(self, world_id: str, user_id: str) -> Optional[Member]:
        return self.db.query(Member).filter(
            Member.world_id == world_id, Member.user_id == user_id,
        ).first()

    # ─── Tiers ──────────────────────────────────────────────────────────
    def list_abonnements(self, world_id: str) -> list[Abonnement]:
        return (
            self.db.query(Abonnement)
            .filter(Abonnement.world_id == world_id, Abonnement.actif == True)
            .all()
        )

    def get_abonnement(self, abonnement_id: str, world_id: Optional[str] = None) -> Optional[Abonnement]:
        q = self.db.query(Abonnement).filter(Abonnement.id == abonnement_id)
        if world_id:
            q = q.filter(Abonnement.world_id == world_id)
        return q.first()

    def add_abonnement(self, abonnement: Abonnement) -> Abonnement:
        self.db.add(abonnement)
        self.db.commit()
        self.db.refresh(abonnement)
        return abonnement

    def update_abonnement(
        self, a: Abonnement, nom: str = "", description: Optional[str] = None, couleur: str = "",
    ) -> Abonnement:
        if nom:
            a.nom = nom
        if description is not None:
            a.description = description
        if couleur:
            a.couleur = couleur
        self.db.commit()
        self.db.refresh(a)
        return a

    def delete_abonnement(self, a: Abonnement) -> None:
        self.db.delete(a)
        self.db.commit()

    # ─── Abonnements d'un membre ────────────────────────────────────────
    def list_membre_abonnements(self, membre_id: str) -> list[MembreAbonnement]:
        return (
            self.db.query(MembreAbonnement)
            .filter(
                MembreAbonnement.member_id == membre_id,
                MembreAbonnement.actif == True,
            )
            .all()
        )

    def get_active_membre_abonnement(
        self, membre_id: str, abonnement_id: str,
    ) -> Optional[MembreAbonnement]:
        return (
            self.db.query(MembreAbonnement)
            .filter(
                MembreAbonnement.member_id == membre_id,
                MembreAbonnement.abonnement_id == abonnement_id,
                MembreAbonnement.actif == True,
            )
            .first()
        )

    def get_any_membre_abonnement(
        self, membre_id: str, abonnement_id: str,
    ) -> Optional[MembreAbonnement]:
        return (
            self.db.query(MembreAbonnement)
            .filter(
                MembreAbonnement.member_id == membre_id,
                MembreAbonnement.abonnement_id == abonnement_id,
            )
            .first()
        )

    def add_membre_abonnement(
        self, membre_id: str, abonnement_id: str,
        assigne_manuellement: bool = False,
        stripe_subscription_id: Optional[str] = None,
    ) -> MembreAbonnement:
        ma = MembreAbonnement(
            member_id=membre_id,
            abonnement_id=abonnement_id,
            actif=True,
            assigne_manuellement=assigne_manuellement,
            stripe_subscription_id=stripe_subscription_id,
        )
        self.db.add(ma)
        self.db.commit()
        return ma

    def delete_membre_abonnement(self, ma: MembreAbonnement) -> None:
        self.db.delete(ma)
        self.db.commit()

    # ─── Stripe webhooks ────────────────────────────────────────────────
    def upsert_membre_abonnement_completion(
        self, membre_id: str, abonnement_id: str, stripe_sub_id: Optional[str],
    ) -> MembreAbonnement:
        existe = self.get_any_membre_abonnement(membre_id, abonnement_id)
        if existe:
            existe.actif = True
            existe.stripe_subscription_id = stripe_sub_id
            self.db.commit()
            return existe
        return self.add_membre_abonnement(
            membre_id=membre_id, abonnement_id=abonnement_id,
            stripe_subscription_id=stripe_sub_id,
        )

    def get_membre_abonnement_by_sub(self, sub_id: str) -> Optional[MembreAbonnement]:
        return (
            self.db.query(MembreAbonnement)
            .filter(MembreAbonnement.stripe_subscription_id == sub_id)
            .first()
        )

    def deactivate_membre_abonnement_by_sub(self, sub_id: str) -> None:
        ma = self.get_membre_abonnement_by_sub(sub_id)
        if ma:
            ma.actif = False
            self.db.commit()


def get_abonnements_service(db: Session = Depends(get_db)) -> AbonnementsService:
    return AbonnementsService(db)
