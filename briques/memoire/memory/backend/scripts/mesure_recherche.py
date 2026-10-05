"""Mesure S238 : ancien algorithme vs nouveau, embedder actif puis coupé.

Charge un corpus synthétique (corpus_mesure.json) dans un espace neuf de la base
TEST_DATABASE_URL, puis rejoue les requêtes annotées. Métriques : rappel@5 (part des
attendus présents dans les 5 premiers), MRR (1/rang du premier attendu), latence p50/p95.

« Ancien » = la requête SQL d'avant S238, recopiée ici telle quelle, avec le comportement
d'avant de l'embedder : en panne, il renvoyait le vecteur constant graine 42.
« Embedder actif » exige un vrai modèle (LLM_BASE_URL, LLM_API_KEY, EMBEDDING_MODEL) :
le script refuse de tourner sans, plutôt que de mesurer un faux embedder.

Usage (depuis backend/) : scripts/en_docker.sh python scripts/mesure_recherche.py
"""
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.config  # noqa: E402

app.config.settings.database_url = os.environ["TEST_DATABASE_URL"]

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.llm.embedder import Embedder  # noqa: E402
from app.migrations_demarrage import appliquer_migrations, vecteur_graine_42  # noqa: E402
from app.models.node import IpCraStage, Node, NodeType  # noqa: E402
from app.models.user import Space  # noqa: E402
from app.services.search_service import SearchService  # noqa: E402

CORPUS = json.loads((Path(__file__).parent / "corpus_mesure.json").read_text())
REPETITIONS = 5


async def ancien(db: AsyncSession, space_id, q: str, vecteur: list[float], limit: int = 20) -> list[uuid.UUID]:
    """Requête d'avant S238 (search_service.hybrid_search au commit f232d8d)."""
    params = {"space_id": space_id, "limit": limit, "embedding": "[" + ",".join(map(str, vecteur)) + "]"}
    mots = q.strip().split()
    conditions = " OR ".join(f"(n.title ILIKE :w{i} OR n.content_md ILIKE :w{i})" for i in range(len(mots)))
    for i, w in enumerate(mots):
        params[f"w{i}"] = f"%{w}%"
    bonus = f"+ CASE WHEN {conditions} THEN 0.3 ELSE 0 END" if mots else ""
    sql = text(f"""
        SELECT n.id, (1 - (n.embedding <=> CAST(:embedding AS vector))) {bonus} AS score
        FROM nodes n
        WHERE n.space_id = :space_id AND n.status IN ('active', 'archived') AND n.embedding IS NOT NULL
        ORDER BY score DESC LIMIT :limit
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]


def metriques(classement: list, attendus: set) -> tuple[float, float]:
    top5 = classement[:5]
    rappel = len(attendus & set(top5)) / len(attendus)
    rr = next((1 / (i + 1) for i, x in enumerate(classement) if x in attendus), 0.0)
    return rappel, rr


async def preparer(fabrique) -> tuple[uuid.UUID, dict]:
    async with fabrique() as db:
        space = Space(name="Mesure S238")
        db.add(space)
        await db.flush()
        emb = Embedder()
        cles = {}
        for s in CORPUS["souvenirs"]:
            n = Node(space_id=space.id, type=NodeType.input, ipcra_stage=IpCraStage.input,
                     title=s["titre"], content_md=s["contenu"],
                     embedding=await emb.embed_text(f"{s['titre']}\n{s['contenu']}"))
            db.add(n)
            await db.flush()
            cles[n.id] = s["cle"]
        await db.commit()
        return space.id, cles


async def mesurer(fabrique, space_id, cles, algo: str, embedder_actif: bool) -> dict:
    par_categorie: dict[str, list[tuple[float, float]]] = {}
    latences = []
    for r in CORPUS["requetes"]:
        attendus = set(r["attendus"])
        for _ in range(REPETITIONS):
            async with fabrique() as db:
                debut = time.perf_counter()
                if algo == "ancien":
                    vecteur = await Embedder().embed_text(r["q"]) if embedder_actif else vecteur_graine_42()
                    ids = await ancien(db, space_id, r["q"], vecteur)
                else:
                    ids = [x.id for x in (await SearchService(db).hybrid_search(space_id, r["q"])).resultats]
                latences.append((time.perf_counter() - debut) * 1000)
        par_categorie.setdefault(r["categorie"], []).append(metriques([cles[i] for i in ids], attendus))
    tout = [m for ms in par_categorie.values() for m in ms]
    return {
        "rappel5": statistics.mean(m[0] for m in tout),
        "mrr": statistics.mean(m[1] for m in tout),
        "p50": statistics.median(latences),
        "p95": statistics.quantiles(latences, n=20)[18],
        "categories": {c: (statistics.mean(m[0] for m in ms), statistics.mean(m[1] for m in ms))
                       for c, ms in par_categorie.items()},
    }


async def principal() -> None:
    if not os.environ.get("LLM_BASE_URL"):
        sys.exit("LLM_BASE_URL absent : la mesure « embedder actif » exige un vrai modèle d'embedding.")
    moteur = create_async_engine(os.environ["TEST_DATABASE_URL"])
    fabrique = async_sessionmaker(moteur, class_=AsyncSession, expire_on_commit=False)
    async with moteur.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await appliquer_migrations(conn)
    space_id, cles = await preparer(fabrique)

    resultats = {}
    for actif in (True, False):
        if not actif:
            async def _panne(self, text):
                raise ConnectionError("embedder coupé pour la mesure")
            LLMClient.embed = _panne
        for algo in ("ancien", "nouveau"):
            resultats[(algo, actif)] = await mesurer(fabrique, space_id, cles, algo, actif)

    categories = sorted({r["categorie"] for r in CORPUS["requetes"]})
    print(f"Corpus : {len(CORPUS['souvenirs'])} souvenirs, {len(CORPUS['requetes'])} requêtes, "
          f"{REPETITIONS} répétitions. Modèle : {app.config.settings.embedding_model}.\n")
    print("| Algorithme | Embedder | Rappel@5 | MRR | p50 (ms) | p95 (ms) | " + " | ".join(categories) + " |")
    print("|---|---|---|---|---|---|" + "---|" * len(categories))
    for (algo, actif), m in resultats.items():
        cats = " | ".join(f"{m['categories'][c][0]:.2f} / {m['categories'][c][1]:.2f}" for c in categories)
        print(f"| {algo} | {'actif' if actif else 'coupé'} | {m['rappel5']:.2f} | {m['mrr']:.2f} | "
              f"{m['p50']:.1f} | {m['p95']:.1f} | {cats} |")
    print("\nCellules par catégorie : rappel@5 / MRR.")
    await moteur.dispose()


if __name__ == "__main__":
    asyncio.run(principal())
