"""Config de test : stockage temporaire, mode API ouvert (déterministe)."""
import os
import tempfile

_DIR = os.path.join(tempfile.gettempdir(), "transferts_brique_test")
os.environ["TRANSFERTS_DIR"] = _DIR
os.environ["TRANSFERTS_DB"] = os.path.join(_DIR, "transferts.db")
os.environ["API_KEYS"] = ""       # mode ouvert : tests n'ont pas à fournir de clé
os.environ["TRANSFERTS_KEY"] = "" # idem pour la route horloge
os.environ.setdefault("TAILLE_PARTIE_OCTETS", "16")   # petites parties : tests rapides
os.environ.setdefault("TAILLE_MAX_OCTETS", "1000000")
os.environ.setdefault("EXPIRATION_MAX_HEURES", "168")
os.environ.setdefault("EXPIRATION_DEFAUT_HEURES", "72")
