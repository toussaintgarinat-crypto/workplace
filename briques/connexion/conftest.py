"""Config de test : mode ouvert/fermé maîtrisé, AUCUN réseau configuré, état dans un tmp.

On purge tous les tokens AVANT le 1er import pour que les adaptateurs soient « non
configurés » par défaut (repli honnête déterministe), et on isole l'état dans un dossier
temporaire (jamais le volume réel). Les tests qui veulent un réseau configuré posent le
token eux-mêmes (monkeypatch.setenv) — les adaptateurs lisent l'env à chaque appel.
"""
import os
import tempfile

os.environ["API_KEYS"] = ""                      # admin en mode ouvert
os.environ["CONNEXION_OUVERT"] = "0"             # consentement requis par défaut
os.environ["CONNEXION_TTS"] = "0"                # pas de synthèse réseau par défaut (déterminisme)
os.environ["CONNEXION_DIR"] = tempfile.mkdtemp(prefix="connexion_test_")

for _v in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET", "WHATSAPP_TOKEN",
           "WHATSAPP_PHONE_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET",
           "DISCORD_PUBLIC_KEY", "DISCORD_BOT_TOKEN", "CONNEXION_RESEAUX",
           "CONNEXION_UTILISATEUR_DEFAUT", "EMAILSMS_FOURNISSEUR", "NOYAU_ASSISTANT_URL",
           "TRANSCRIPTION_URL", "TRANSCRIPTION_KEY", "VOIX_URL", "VOIX_KEY"):
    os.environ.pop(_v, None)
