-- S239 (revue I2) — presets LLM de la Forge : ancien défaut Go → alias Gateway `forge/defaut`.
--
-- À EXÉCUTER À LA MAIN au déploiement, APRÈS sauvegarde de forge-db — ce n'est PAS une
-- migration automatique (décision : aucune réécriture de données sans regard humain).
--   docker exec -i <conteneur forge-db> psql -U forge -d forge < s239_presets_forge_defaut.sql
--
-- Pourquoi. Les presets de pôle étaient créés sans provider/model : la base les remplissait
-- avec le défaut de colonne `opencode` / `go/deepseek-v4-flash` (abonnement Go en pause
-- depuis 2026-10-05 → 400/401, la Forge ne répondait plus). Le code pose désormais ces
-- valeurs explicitement (app/llm.py:preset_pole_defaut), mais les lignes DÉJÀ en base
-- restent sur Go.
--
-- Périmètre strict : seules les lignes valant EXACTEMENT l'ancien défaut (le couple
-- provider + modèle) sont modifiées. Un preset choisi à la main (autre modèle, ou go/* avec
-- un autre provider) n'est pas touché. Idempotent : rejouer ne change plus rien.

BEGIN;

-- Aperçu de ce qui va changer (à lire dans la sortie psql).
SELECT scope_type, count(*) AS presets_a_migrer
FROM llm_presets
WHERE provider = 'opencode' AND model = 'go/deepseek-v4-flash'
GROUP BY scope_type;

UPDATE llm_presets SET provider = 'gateway', model = 'forge/defaut', updated_at = now() WHERE provider = 'opencode' AND model = 'go/deepseek-v4-flash';

-- Défaut de colonne aligné sur les bases neuves (create_all n'altère pas une table
-- existante). Opération de schéma, idempotente, sans effet sur les lignes.
ALTER TABLE llm_presets ALTER COLUMN provider SET DEFAULT 'gateway';
ALTER TABLE llm_presets ALTER COLUMN model SET DEFAULT 'forge/defaut';

COMMIT;
