"""Résolution des rappels effectifs d'un participant (S174). Pur, sans I/O.

NULL (participant.rappels) = hérite du défaut de l'événement ; [] = aucun rappel
explicite ; [m, …] = override personnel. Consommé par l'agrégation /service/events,
lue par le proactif du Cœur pour pousser un rappel par personne."""

from __future__ import annotations


def rappels_effectifs(participant_rappels: list[int] | None,
                      event_rappels: list[int]) -> list[int]:
    """Rappels réellement dus pour ce participant : son override s'il existe, sinon le
    défaut de l'événement."""
    return participant_rappels if participant_rappels is not None else event_rappels
