-- Extensions requises par le backend Memory, activées à l'init du volume (avant la création
-- des tables). pgvector : colonne Vector(384). unaccent + pg_trgm : recherche lexicale S238
-- (le backend les active aussi au démarrage, pour les volumes déjà initialisés).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
