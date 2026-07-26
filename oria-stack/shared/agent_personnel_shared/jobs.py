"""Jobs de fond durables via Redis Streams + consumer groups (S125).

Pourquoi : avant S125, les jobs lourds (swarm de l'assistant, parsing de
documents Oria) vivaient en **mémoire de process** (``asyncio.Task`` /
``BackgroundTasks``). Conséquences au multi-réplica / au restart :
- travail **perdu** si le process redémarre en cours de route ;
- pas de **retry** ni de **reprise** ;
- concurrence **par process** (cap × N réplicas) au lieu de globale ;
- une tâche ne vit que sur le réplica qui l'a lancée (pas de file partagée).

Redis Streams + consumer groups règlent tout ça sans nouveau service à opérer
(Redis est déjà partout : pub/sub SSE, leader election S123, namespacing S101) :
- **ACK par message** : un job n'est retiré de la file qu'une fois traité ;
- **reprise au crash** : les messages livrés mais non-ack sont relus via
  ``XAUTOCLAIM`` (orphelins d'un réplica mort) ;
- **file partagée** : le consumer group distribue chaque message à un seul
  consumer, quel que soit le réplica ;
- **concurrence globale** : un sémaphore distribué (ZSET) borne le nombre de
  jobs traités *simultanément, tous réplicas confondus* — pas ``cap × N`` ;
- **dead-letter** : après ``max_retries`` échecs, le message part en
  ``…:dlq`` + callback d'alerte, sans bloquer la file.

Sans Redis (mono-instance, ``REDIS_URL`` vide) : ``JobWorker.enqueue`` retombe
sur un ``asyncio.Task`` local — comportement identique à l'ancien monde, mais
toujours borné par la concurrence locale.

Convention de clés (namespacing S101) :
    {namespace}:jobs:{stream}            → le stream principal
    {namespace}:jobs:{stream}:dlq        → dead-letter queue
    {namespace}:jobs:{stream}:retries    → hash {msg_id: nb_tentatives}
    {namespace}:jobs:{stream}:slots      → ZSET sémaphore concurrence globale
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid as _uuid
from typing import Any, Awaitable, Callable, Optional

from .redis_client import get_raw_client

logger = logging.getLogger(__name__)

# Identifiant unique de ce process — sert de préfixe aux noms de consumer.
_PROCESS_ID = str(_uuid.uuid4())[:8]

# ── Métriques Prometheus (optionnelles) ──────────────────────────────────
# Le paquet partagé ne dépend pas de prometheus_client ; on l'importe au mieux.
try:  # pragma: no cover - dépend de l'hôte
    from prometheus_client import Gauge

    _JOB_DEPTH = Gauge(
        "job_queue_depth", "Profondeur du stream de jobs (XLEN)",
        ["namespace", "stream"],
    )
    _JOB_PENDING = Gauge(
        "job_queue_pending", "Messages livrés mais non ack (XPENDING)",
        ["namespace", "stream"],
    )
    _JOB_DLQ = Gauge(
        "job_dlq_size", "Taille de la dead-letter queue",
        ["namespace", "stream"],
    )
except Exception:  # pragma: no cover
    _JOB_DEPTH = _JOB_PENDING = _JOB_DLQ = None


Handler = Callable[[dict], Awaitable[None]]
DLQHook = Callable[[dict, str], Awaitable[None]]


# Sémaphore distribué (counting) : on évince les détenteurs périmés (crash)
# avant de compter, ce qui rend le slot auto-libérable après expiration.
_ACQUIRE_SLOT = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('zremrangebyscore', KEYS[1], '-inf', now - ttl)
if redis.call('zcard', KEYS[1]) < limit then
    redis.call('zadd', KEYS[1], now, ARGV[4])
    redis.call('expire', KEYS[1], math.ceil(ttl * 2))
    return 1
end
return 0
"""


async def enqueue(
    namespace: str,
    stream: str,
    payload: dict,
    *,
    maxlen: int = 10000,
) -> Optional[str]:
    """Empile un job (``XADD``) sur ``{namespace}:jobs:{stream}``.

    Retourne l'id du message, ou ``None`` si Redis est indisponible (l'appelant
    — typiquement ``JobWorker.enqueue`` — bascule alors en exécution locale).
    Le stream est borné par ``MAXLEN ~`` (trim approximatif, peu coûteux).
    """
    client = get_raw_client()
    if client is None:
        return None
    key = f"{namespace}:jobs:{stream}"
    data = json.dumps(payload, ensure_ascii=False)
    return await client.xadd(key, {"data": data}, maxlen=maxlen, approximate=True)


class JobWorker:
    """Consumer durable d'un stream de jobs.

    L'hôte fournit un ``handler`` async ``(payload) -> None``. Une exception
    levée par le handler laisse le message *pending* : il sera relu (retry) par
    la boucle de reclaim, jusqu'à ``max_retries`` puis dirigé vers la DLQ.

    Paramètres :
      - ``concurrency`` : nombre de boucles de lecture (et plafond local) sur
        ce réplica.
      - ``global_concurrency`` : plafond *global* (tous réplicas) de jobs en
        cours ; ``0`` = désactivé (seul le plafond local s'applique).
      - ``max_retries`` : nb de tentatives avant DLQ.
      - ``on_dlq`` : callback async ``(payload, error)`` au passage en DLQ.
    """

    def __init__(
        self,
        namespace: str,
        stream: str,
        group: str,
        handler: Handler,
        *,
        concurrency: int = 1,
        global_concurrency: int = 0,
        max_retries: int = 3,
        block_ms: int = 5000,
        claim_min_idle_ms: int = 60000,
        reclaim_interval_s: float = 30.0,
        slot_ttl_s: int = 1800,
        on_dlq: Optional[DLQHook] = None,
    ) -> None:
        self.namespace = namespace
        self.stream = stream
        self.group = group
        self._handler = handler
        self.concurrency = max(1, concurrency)
        self.global_concurrency = max(0, global_concurrency)
        self.max_retries = max(0, max_retries)
        self.block_ms = block_ms
        self.claim_min_idle_ms = claim_min_idle_ms
        self.reclaim_interval_s = reclaim_interval_s
        self.slot_ttl_s = slot_ttl_s
        self._on_dlq = on_dlq

        self.key = f"{namespace}:jobs:{stream}"
        self.dlq_key = f"{self.key}:dlq"
        self.retries_key = f"{self.key}:retries"
        self.slots_key = f"{self.key}:slots"

        self._tasks: list[asyncio.Task] = []
        self._local_sem = asyncio.Semaphore(self.concurrency)
        self._stop = False

    # ── Cycle de vie ─────────────────────────────────────────────────────
    async def start(self) -> None:
        """Crée le consumer group puis lance les boucles de lecture + reclaim.

        No-op si Redis est absent : dans ce mode ``enqueue`` exécute en local.
        """
        client = get_raw_client()
        if client is None:
            logger.info(
                "JobWorker[%s] sans Redis — exécution locale (mono-instance)", self.key
            )
            return
        await self._ensure_group(client)
        self._stop = False
        for i in range(self.concurrency):
            consumer = f"{_PROCESS_ID}-{i}"
            self._tasks.append(asyncio.create_task(self._reader_loop(consumer)))
        self._tasks.append(asyncio.create_task(self._reclaim_loop()))
        logger.info(
            "JobWorker[%s] démarré : %d consumers, global_cap=%s, max_retries=%d",
            self.key, self.concurrency, self.global_concurrency or "off", self.max_retries,
        )

    async def stop(self) -> None:
        self._stop = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()

    async def enqueue(self, payload: dict) -> Optional[str]:
        """Empile un job. Sans Redis → exécution locale immédiate (asyncio)."""
        msg_id = await enqueue(self.namespace, self.stream, payload)
        if msg_id is None:
            # Mode dégradé : pas de stream → on lance le handler en local,
            # toujours borné par la concurrence locale (best effort, sans DLQ).
            asyncio.create_task(self._run_local(payload))
        return msg_id

    # ── Boucles ──────────────────────────────────────────────────────────
    async def _ensure_group(self, client: Any) -> None:
        try:
            # id="0" : le group consomme aussi un éventuel backlog déjà présent.
            await client.xgroup_create(self.key, self.group, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001
            if "BUSYGROUP" not in str(exc):
                raise

    async def _reader_loop(self, consumer: str) -> None:
        client = get_raw_client()
        while not self._stop:
            try:
                resp = await client.xreadgroup(
                    self.group, consumer, {self.key: ">"},
                    count=1, block=self.block_ms,
                )
                if not resp:
                    continue
                for _stream, entries in resp:
                    for msg_id, fields in entries:
                        await self._handle(client, msg_id, fields, consumer)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("JobWorker[%s] reader error: %s", self.key, exc)
                await asyncio.sleep(1)

    async def _reclaim_loop(self) -> None:
        client = get_raw_client()
        while not self._stop:
            try:
                await asyncio.sleep(self.reclaim_interval_s)
                await self._reclaim_once(client)
                await self._publish_metrics(client)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("JobWorker[%s] reclaim error: %s", self.key, exc)

    async def _reclaim_once(self, client: Any) -> None:
        """Reprend les messages orphelins (livrés mais jamais ack par un réplica
        mort) au-delà de ``claim_min_idle_ms`` via ``XAUTOCLAIM``."""
        cursor = "0-0"
        consumer = f"{_PROCESS_ID}-reclaim"
        while not self._stop:
            res = await client.xautoclaim(
                self.key, self.group, consumer,
                min_idle_time=self.claim_min_idle_ms, start_id=cursor, count=10,
            )
            # redis-py : [cursor, messages] ou [cursor, messages, deleted_ids].
            cursor = res[0]
            messages = res[1]
            for msg_id, fields in messages:
                if fields is None:
                    # Message supprimé du stream entre-temps → on ack et nettoie.
                    await client.xack(self.key, self.group, msg_id)
                    await client.hdel(self.retries_key, msg_id)
                    continue
                await self._handle(client, msg_id, fields, consumer)
            if not messages or cursor in ("0-0", 0):
                break

    # ── Traitement d'un message ──────────────────────────────────────────
    async def _handle(self, client: Any, msg_id: str, fields: dict, consumer: str) -> None:
        payload = self._parse(fields)
        # Numéro de cette tentative (1 = première livraison). Incrémenté à chaque
        # (re)livraison — reader OU reclaim.
        attempts = await client.hincrby(self.retries_key, msg_id, 1)

        if attempts > self.max_retries:
            # Les `max_retries` tentatives précédentes ont échoué → DLQ sans
            # rejouer le handler.
            await self._to_dlq(client, msg_id, payload,
                               f"échec après {self.max_retries} tentative(s)")
            return

        member = f"{consumer}:{msg_id}"
        await self._acquire_slot(client, member)
        try:
            async with self._local_sem:
                await self._handler(payload)
            await client.xack(self.key, self.group, msg_id)
            await client.hdel(self.retries_key, msg_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "JobWorker[%s] job %s échec tentative %d/%d: %s",
                self.key, msg_id, attempts, self.max_retries, exc,
            )
            # On laisse le message *pending* → relu par la boucle de reclaim.
        finally:
            await self._release_slot(client, member)

    async def _to_dlq(self, client: Any, msg_id: str, payload: dict, error: str) -> None:
        try:
            await client.xadd(self.dlq_key, {
                "data": json.dumps(payload, ensure_ascii=False),
                "error": error[:500],
                "orig_id": str(msg_id),
            }, maxlen=10000, approximate=True)
            await client.xack(self.key, self.group, msg_id)
            await client.hdel(self.retries_key, msg_id)
            logger.error("JobWorker[%s] job %s → DLQ: %s", self.key, msg_id, error)
            if self._on_dlq is not None:
                try:
                    await self._on_dlq(payload, error)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("JobWorker[%s] on_dlq hook a échoué: %s", self.key, exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("JobWorker[%s] impossible d'écrire en DLQ: %s", self.key, exc)

    async def _run_local(self, payload: dict) -> None:
        """Exécution dégradée sans Redis : pas de retry/DLQ, best effort."""
        try:
            async with self._local_sem:
                await self._handler(payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("JobWorker[%s] job local échoué: %s", self.key, exc)

    # ── Sémaphore de concurrence globale ─────────────────────────────────
    async def _acquire_slot(self, client: Any, member: str) -> None:
        if self.global_concurrency <= 0:
            return
        delay = 0.2
        while not self._stop:
            ok = await client.eval(
                _ACQUIRE_SLOT, 1, self.slots_key,
                str(time.time()), str(self.slot_ttl_s),
                str(self.global_concurrency), member,
            )
            if ok:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 2.0)

    async def _release_slot(self, client: Any, member: str) -> None:
        if self.global_concurrency <= 0:
            return
        try:
            await client.zrem(self.slots_key, member)
        except Exception:  # noqa: BLE001
            pass

    # ── Observabilité ────────────────────────────────────────────────────
    async def stats(self) -> dict:
        client = get_raw_client()
        if client is None:
            return {"redis": False}
        depth = await client.xlen(self.key)
        dlq = await client.xlen(self.dlq_key)
        try:
            pend = await client.xpending(self.key, self.group)
            pending = pend["pending"] if isinstance(pend, dict) else (pend[0] if pend else 0)
        except Exception:  # noqa: BLE001
            pending = 0
        return {"redis": True, "depth": depth, "pending": pending, "dlq": dlq}

    async def _publish_metrics(self, client: Any) -> None:
        if _JOB_DEPTH is None:
            return
        try:
            s = await self.stats()
            if s.get("redis"):
                _JOB_DEPTH.labels(self.namespace, self.stream).set(s["depth"])
                _JOB_PENDING.labels(self.namespace, self.stream).set(s["pending"])
                _JOB_DLQ.labels(self.namespace, self.stream).set(s["dlq"])
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _parse(fields: dict) -> dict:
        raw = fields.get("data") if isinstance(fields, dict) else None
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
