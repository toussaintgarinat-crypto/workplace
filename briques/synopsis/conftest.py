"""Config de test : coupe tous les appels externes (YouTube, LLM, ffmpeg)."""
import os

os.environ["API_KEYS"] = ""
os.environ["GATEWAY_URL"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["OPENCODE_GO_API_KEY"] = ""
