"""Rate limiting en mémoire par IP — mono-process (V1, décision de cadrage scaling, cf.
spec § Anti-abus). Se réinitialise au redémarrage du process : acceptable tant qu'il n'y a
qu'un seul process (pas de scaling horizontal en V1)."""
import time

FENETRE_S = 300       # 5 minutes
MAX_TENTATIVES = 10

_tentatives: dict[str, list[float]] = {}


def autorise(ip: str, maintenant: float | None = None) -> bool:
    maintenant = maintenant if maintenant is not None else time.monotonic()
    horodatages = [t for t in _tentatives.get(ip, []) if maintenant - t < FENETRE_S]
    horodatages.append(maintenant)
    _tentatives[ip] = horodatages
    return len(horodatages) <= MAX_TENTATIVES


def _reinitialiser() -> None:
    _tentatives.clear()
