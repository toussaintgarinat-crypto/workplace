"""Catalogue tap-to-add façon Bring! : rayons FR + items intégrés semés au boot."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import CatalogItem

# Ordre = ordre d'affichage des rayons dans le front.
RAYONS: list[str] = [
    "Fruits & légumes", "Crèmerie", "Boulangerie", "Boucherie-Poissonnerie",
    "Épicerie salée", "Épicerie sucrée", "Boissons", "Surgelés",
    "Hygiène", "Entretien", "Bébé", "Animaux", "Autre",
]

# (emoji, nom, rayon)
CATALOGUE_DEFAUT: list[tuple[str, str, str]] = [
    ("🍎", "Pommes", "Fruits & légumes"), ("🍌", "Bananes", "Fruits & légumes"),
    ("🍅", "Tomates", "Fruits & légumes"), ("🥕", "Carottes", "Fruits & légumes"),
    ("🥔", "Pommes de terre", "Fruits & légumes"), ("🧅", "Oignons", "Fruits & légumes"),
    ("🥗", "Salade", "Fruits & légumes"), ("🍋", "Citrons", "Fruits & légumes"),
    ("🥦", "Brocoli", "Fruits & légumes"), ("🍓", "Fraises", "Fruits & légumes"),
    ("🥛", "Lait", "Crèmerie"), ("🧀", "Fromage", "Crèmerie"),
    ("🧈", "Beurre", "Crèmerie"), ("🥚", "Œufs", "Crèmerie"),
    ("🍦", "Yaourts", "Crèmerie"), ("🥫", "Crème fraîche", "Crèmerie"),
    ("🥖", "Baguette", "Boulangerie"), ("🍞", "Pain de mie", "Boulangerie"),
    ("🥐", "Croissants", "Boulangerie"), ("🍩", "Viennoiseries", "Boulangerie"),
    ("🍗", "Poulet", "Boucherie-Poissonnerie"), ("🥩", "Steak haché", "Boucherie-Poissonnerie"),
    ("🍖", "Jambon", "Boucherie-Poissonnerie"), ("🐟", "Poisson", "Boucherie-Poissonnerie"),
    ("🍝", "Pâtes", "Épicerie salée"), ("🍚", "Riz", "Épicerie salée"),
    ("🥫", "Conserves", "Épicerie salée"), ("🧂", "Sel", "Épicerie salée"),
    ("🫒", "Huile", "Épicerie salée"), ("🍲", "Soupe", "Épicerie salée"),
    ("🥣", "Céréales", "Épicerie sucrée"), ("☕", "Café", "Épicerie sucrée"),
    ("🍫", "Chocolat", "Épicerie sucrée"), ("🍪", "Biscuits", "Épicerie sucrée"),
    ("🍯", "Miel", "Épicerie sucrée"), ("🍬", "Sucre", "Épicerie sucrée"),
    ("💧", "Eau", "Boissons"), ("🧃", "Jus de fruits", "Boissons"),
    ("🥤", "Sodas", "Boissons"), ("🍷", "Vin", "Boissons"), ("🍺", "Bière", "Boissons"),
    ("🍕", "Pizza surgelée", "Surgelés"), ("🧊", "Glaçons", "Surgelés"),
    ("🥟", "Légumes surgelés", "Surgelés"),
    ("🧼", "Savon", "Hygiène"), ("🪥", "Dentifrice", "Hygiène"),
    ("🧻", "Papier toilette", "Hygiène"), ("🧴", "Shampoing", "Hygiène"),
    ("🧽", "Éponges", "Entretien"), ("🧺", "Lessive", "Entretien"),
    ("🧹", "Sac poubelle", "Entretien"), ("🫧", "Liquide vaisselle", "Entretien"),
    ("🍼", "Petits pots", "Bébé"), ("👶", "Couches", "Bébé"),
    ("🐕", "Croquettes chien", "Animaux"), ("🐈", "Litière chat", "Animaux"),
]


async def semer_catalogue(db: AsyncSession) -> int:
    """Insère le catalogue intégré (list_id NULL) une seule fois. Renvoie le nb inséré."""
    count = await db.scalar(
        select(func.count()).select_from(CatalogItem).where(CatalogItem.list_id.is_(None))
    )
    if count:
        return 0
    for emoji, nom, rayon in CATALOGUE_DEFAUT:
        db.add(CatalogItem(list_id=None, name=nom, emoji=emoji, rayon=rayon))
    await db.commit()
    return len(CATALOGUE_DEFAUT)


async def catalogue_pour_liste(db: AsyncSession, list_id: str) -> list[CatalogItem]:
    """Catalogue visible pour une liste = intégrés (NULL) ∪ perso de cette liste."""
    res = await db.execute(
        select(CatalogItem).where(
            (CatalogItem.list_id.is_(None)) | (CatalogItem.list_id == list_id)
        )
    )
    return list(res.scalars().all())


async def memoriser_item_perso(
    db: AsyncSession, list_id: str, nom: str, emoji: str | None, rayon: str | None, user_id: str
) -> CatalogItem | None:
    """Ajoute un item perso au catalogue de la liste s'il n'existe pas déjà
    (dédup insensible à la casse, contre intégrés + perso). Renvoie l'entrée créée ou None."""
    existants = await catalogue_pour_liste(db, list_id)
    if any(c.name.strip().lower() == nom.strip().lower() for c in existants):
        return None
    item = CatalogItem(
        list_id=list_id, name=nom, emoji=emoji or "🛒",
        rayon=rayon if rayon in RAYONS else "Autre", created_by=user_id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item
