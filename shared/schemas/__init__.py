"""Schémas de contrat PARTAGÉS entre briques (S119).

Modèles Pydantic figeant les charges utiles qui circulent d'une brique à l'autre,
pour que producteur et consommateur s'accordent sur une source unique (plus de dict
implicite divergent). Premier contrat : `audit` (brique audit → brique générateur).
"""
