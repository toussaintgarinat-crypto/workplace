"""Config de test : aucune clé API configurée → mode ouvert, déterministe."""
import os

os.environ["API_KEYS"] = ""
for _v in ("CONNEXION_URL", "CONNEXION_KEY", "VOIX_URL", "VOIX_KEY",
           "TRANSCRIPTION_URL", "TRANSCRIPTION_KEY", "MESSAGES_DB", "MESSAGES_DIR"):
    os.environ.pop(_v, None)
