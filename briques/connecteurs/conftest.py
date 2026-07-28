"""Config de test : DB temporaire et clés AVANT tout import des modules applicatifs."""
import os
import tempfile

_travail = tempfile.mkdtemp(prefix="connecteurs-test-")
os.environ["CONNECTEURS_DB"] = os.path.join(_travail, "connecteurs_test.db")
os.environ["CONNECTEURS_TRAVAIL"] = os.path.join(_travail, "travail")
# Clé de chiffrement déterministe : les configs de source sont chiffrées même en test
# (le contraire laisserait passer une régression où l'on écrit en clair sans le voir).
os.environ["CONNECTEURS_ENCRYPTION_KEY"] = "cle-de-test-connecteurs-0123456789"
os.environ.pop("API_KEYS", None)        # clés libres en test (isolation par empreinte)
os.environ.pop("CONNECTEURS_KEY", None)  # /sync/executer ouvert en test
