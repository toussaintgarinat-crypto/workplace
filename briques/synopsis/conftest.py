"""Config de test : coupe tous les appels externes (YouTube, LLM, ffmpeg)."""
import os
import tempfile

os.environ["API_KEYS"] = ""
os.environ["GATEWAY_URL"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["OPENCODE_GO_API_KEY"] = ""
os.environ.setdefault("JOBS_DB", os.path.join(tempfile.gettempdir(), "synopsis-test-jobs.db"))
