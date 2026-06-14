"""Config de test : volume de séries temporaire AVANT tout import des modules.

Les modules `studio`/`main` créent `STUDIO_DIR` à l'import → on le pointe vers un temp dir
pour ne jamais toucher le volume réel ni écrire dans /data hors conteneur."""
import os
import tempfile

os.environ.setdefault("STUDIO_DIR", os.path.join(tempfile.gettempdir(), "studio_test_ateliers"))
os.environ.setdefault("API_KEYS", "")   # mode ouvert → identité "public"
os.makedirs(os.environ["STUDIO_DIR"], exist_ok=True)
