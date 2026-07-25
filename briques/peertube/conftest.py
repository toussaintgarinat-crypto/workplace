import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["AUDIT_FICHIERS_URL"] = ""   # no-op en test : pas de dépendance réseau (S195)
