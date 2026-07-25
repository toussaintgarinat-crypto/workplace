"""Config de test : mode API ouvert (déterministe), aucune dépendance réseau réelle
à ClamAV (le protocole clamd est mocké dans test_moteur_clamav.py/test_api.py)."""
import os

os.environ["API_KEYS"] = ""
os.environ["CLAMAV_HOSTS"] = "localhost:9999"   # jamais réellement contacté en test
