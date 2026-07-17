"""Icônes PWA générées LOCALEMENT (aucun CDN, règle projet). MVP : carré uni au thème
sombre/or de l'app — suffisant pour une PWA installable. Glyphe = fast-follow."""
from __future__ import annotations

import struct
import zlib

FOND = (26, 22, 18)   # #1A1612, brun sombre du thème


def _chunk(typ: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def png_icone(taille: int, maskable: bool = False) -> bytes:
    """PNG carré `taille`×`taille` de couleur unie (thème). `maskable` = même image
    (la safe-zone est respectée puisque le fond est plein)."""
    r, g, b = FOND
    ligne = b"\x00" + bytes([r, g, b]) * taille       # filtre 0 + pixels RGB
    brut = ligne * taille
    ihdr = struct.pack(">IIBBBBB", taille, taille, 8, 2, 0, 0, 0)  # 8 bits, RGB
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(brut, 9))
            + _chunk(b"IEND", b""))
