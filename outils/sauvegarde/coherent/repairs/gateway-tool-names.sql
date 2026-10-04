-- S236: retain every tool ID and payload; keep earliest registration as canonical.
-- Execute only after private full pg_dump and isolated proof. Transaction fails closed.
BEGIN;
SET LOCAL lock_timeout = '10s';
LOCK TABLE public."LiteLLM_ToolTable" IN ACCESS EXCLUSIVE MODE;
SET LOCAL enable_indexscan = off;
SET LOCAL enable_indexonlyscan = off;
SET LOCAL enable_bitmapscan = off;
CREATE SCHEMA s236_recovery;
CREATE TABLE s236_recovery.gateway_tool_original AS
SELECT t.* FROM public."LiteLLM_ToolTable" t
JOIN (SELECT tool_name COLLATE "C" AS name FROM public."LiteLLM_ToolTable"
 GROUP BY tool_name COLLATE "C" HAVING count(*) > 1) d
ON t.tool_name COLLATE "C" = d.name;
CREATE TEMP TABLE renames ON COMMIT DROP AS
SELECT tool_id, tool_name || '__s236_recovered_' || tool_id AS recovered_name
FROM (SELECT tool_id,tool_name,row_number() OVER
 (PARTITION BY tool_name COLLATE "C" ORDER BY created_at,tool_id COLLATE "C") n
 FROM public."LiteLLM_ToolTable") t WHERE n > 1;
DO $$ BEGIN
 IF (SELECT count(*) FROM s236_recovery.gateway_tool_original) <> 42
 OR (SELECT count(*) FROM renames) <> 21
 THEN RAISE EXCEPTION 'Unexpected duplicate inventory'; END IF;
 IF EXISTS(SELECT 1 FROM renames r JOIN public."LiteLLM_ToolTable" t
 ON t.tool_name COLLATE "C" = r.recovered_name COLLATE "C")
 THEN RAISE EXCEPTION 'Recovery name collision'; END IF;
END $$;
DROP INDEX IF EXISTS public."LiteLLM_ToolTable_tool_name_key";
UPDATE public."LiteLLM_ToolTable" t SET tool_name=r.recovered_name
FROM renames r WHERE t.tool_id=r.tool_id;
CREATE UNIQUE INDEX "LiteLLM_ToolTable_tool_name_key"
 ON public."LiteLLM_ToolTable" USING btree(tool_name);
DO $$ BEGIN
 IF (SELECT count(*) FROM public."LiteLLM_ToolTable") <> 367
 OR EXISTS(SELECT 1 FROM s236_recovery.gateway_tool_original o
 JOIN public."LiteLLM_ToolTable" t USING(tool_id)
 WHERE to_jsonb(o)-'tool_name' <> to_jsonb(t)-'tool_name')
 OR (SELECT count(*) FROM s236_recovery.gateway_tool_original o
 JOIN public."LiteLLM_ToolTable" t USING(tool_id)) <> 42
 THEN RAISE EXCEPTION 'Tool payload conservation failed'; END IF;
END $$;
COMMIT;
