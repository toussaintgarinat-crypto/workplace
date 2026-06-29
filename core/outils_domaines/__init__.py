"""Modules de dispatch des outils par domaine (S115). Chacun expose
`async def dispatch(nom, args, registre, client) -> str | None`.
"""
from . import (
    systeme, amelioration, documents, agenda, forge, usine, studio, transcription
)
