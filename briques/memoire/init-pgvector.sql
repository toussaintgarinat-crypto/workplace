-- Active l'extension pgvector AVANT que le backend Memory ne crée ses tables
-- (le modèle Node a une colonne Vector(384)). Exécuté une fois à l'init du volume.
CREATE EXTENSION IF NOT EXISTS vector;
