"""Config de test : stockage temporaire + mode API ouvert (déterministe)."""
import os
import tempfile

os.environ["FICHIERS_DIR"] = os.path.join(tempfile.gettempdir(), "export_brique_test")
os.environ["API_KEYS"] = ""   # mode ouvert : tests n'ont pas à fournir de clé
