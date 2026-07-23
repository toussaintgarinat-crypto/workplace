"""Config de test : environnement neutre (mode ouvert) pour des tests déterministes, quel
que soit le shell — sinon un vrai secret de service traînant dans l'env changerait le
comportement testé (même motif que briques/images/conftest.py)."""
import os

for _v in ("ATELIER_IMAGES_VIDEO_KEY", "STUDIO_KEY", "MEMOIRE_KEY"):
    os.environ.pop(_v, None)
