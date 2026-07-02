"""Config de test : mode ouvert + un parc déterministe pointant des ports LOOPBACK fermés.

Aucun réseau externe : un port loopback fermé renvoie un « connection refused » immédiat,
ce qui rend les sondes reproductibles et hors-ligne. Les délais de réveil sont mis à 0 pour
que les tests d'API ne bouclent pas.
"""
import json
import os

os.environ["API_KEYS"] = ""                       # mode ouvert
# Neutralise le fichier de parc persisté en tests : pointe sur un chemin inexistant
# pour que charger_parc() retombe uniquement sur CALCUL_NOEUDS (2 nœuds) et que les
# assertions existantes (noeuds == 2) restent vraies quelle que soit la machine.
os.environ["CALCUL_PARC_FILE"] = "/tmp/calcul-test-parc-inexistant.json"
os.environ["CALCUL_NOEUDS"] = json.dumps([
    {"id": "muscle", "nom": "Mac Studio", "endpoint": "http://127.0.0.1:59999",
     "methode_reveil": ["wakeping"], "reveil_timeout_s": 0, "intervalle_sonde_s": 0.01,
     "priorite": 10, "modele_gateway": "ollama/llama3.3"},
    {"id": "fixe", "endpoint": "http://127.0.0.1:59998/", "methode_reveil": ["aucun"],
     "priorite": 50},
])
