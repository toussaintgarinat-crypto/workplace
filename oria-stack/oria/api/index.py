import sys
import os

# Ajoute le dossier backend au path Python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from main import app
