"""SpearCode — mini-IDE web greffé dans la brique `dev` (porté de Gungnir).

La brique `dev` GARDE sa logique d'auto-atelier (worktree jetable + agents Claude Code/
OpenCode + plan BMAD + gates + git_atelier.py). On y AJOUTE l'IDE navigateur SpearCode du
plugin `code` de Gungnir : explorateur de fichiers, lecture/écriture, upload/download,
recherche, exécution bornée, formatage, versions locales et snippets.

DÉCOUPLAGE vs Gungnir : le plugin original isolait tout PAR-UTILISATEUR (ContextVar +
table User + clés providers en base + rate-limit slowapi). La brique `dev` est MONO-USER
souveraine (cf. main.py) → ce package fournit des helpers à workspace UNIQUE, sans base ni
ContextVar par-requête, et un rate-limiter no-op. Les sous-modules `files`/`exec`/`format`/
`versions`/`snippets` sont repris quasi verbatim et importent leurs helpers d'ici.

NON portés (volontaire) :
  • `ai.py`  — assistant de code couplé au stack LLM/providers de Gungnir ; la brique `dev`
               a déjà ses agents (agents.py : Claude Code / OpenCode) pour coder.
  • `git.py` — UI git générique ; la logique git de l'atelier (worktrees, gates) est
               `git_atelier.py`, qu'on garde (consigne « garde ma logique »).
  • `lsp/`   — nécessite des serveurs de langage installés (lourd) ; hors périmètre.

Sécurité conservée : `_safe_path` bloque la traversée de répertoire ET l'évasion par
symlink ; l'exécution est bornée (timeout, env nettoyé des secrets, patterns destructeurs
refusés). Le workspace est confiné à `DEV_IDE_WORKSPACE` (+ racines autorisées explicites).
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("workplace.dev.spearcode")

# Router de l'IDE. Monté sous /ide par main.py (préfixe). Pas de dépendance per-user.
router = APIRouter()


# ── Rate-limiter no-op (mono-user : pas de slowapi) ──────────────────────────
class _NoLimiter:
    """Remplace slowapi.Limiter : décorateur identité (atelier mono-user souverain)."""
    def limit(self, *_a, **_k):
        def deco(fn):
            return fn
        return deco


limiter_code = _NoLimiter()

# ContextVar de compat (snippets per-user en amont) : mono-user → toujours 0.
from contextvars import ContextVar  # noqa: E402
_current_user_id: ContextVar[int] = ContextVar("_current_user_id", default=0)


# ── Workspace (unique, confiné) + données locales ─────────────────────────────

_HERE = Path(__file__).parent.parent.resolve()             # briques/dev/
WORKSPACE_ROOT = Path(os.environ.get("DEV_IDE_WORKSPACE",
                                     str(_HERE / "ide-workspace"))).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# Racines supplémentaires autorisées pour un override de workspace (CSV de chemins).
_ALLOW_ROOTS = [WORKSPACE_ROOT] + [
    Path(p).expanduser().resolve()
    for p in os.environ.get("DEV_IDE_ALLOW_ROOTS", "").split(os.pathsep) if p.strip()
]

DATA_DIR = Path(os.environ.get("DEV_IDE_DATA", str(_HERE / "ide-data"))).resolve()
_CONFIG_FILE = DATA_DIR / "code_config.json"
VERSIONS_DIR = DATA_DIR / "code_versions"
SNIPPETS_DIR = DATA_DIR / "code_snippets"

IGNORE_DIRS = {"node_modules", ".git", "dist", "build", ".next", "__pycache__",
               ".venv", "venv", ".spearcode"}


def _is_allowed_workspace(p: Path) -> bool:
    """Le workspace doit rester sous une racine autorisée (anti-évasion)."""
    resolved = p.resolve()
    for root in _ALLOW_ROOTS:
        if resolved == root:
            return True
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _load_config() -> dict:
    default = {"workspace": str(WORKSPACE_ROOT), "recent_files": [], "font_size": 14}
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            return {**default, **(data or {})}
        except Exception:  # noqa: BLE001
            pass
    return default


def _save_config(cfg: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _workspace() -> Path:
    """Workspace effectif : valeur de config si autorisée, sinon la racine par défaut."""
    try:
        configured = _load_config().get("workspace")
    except Exception:  # noqa: BLE001
        configured = None
    if configured:
        try:
            p = Path(configured).resolve()
            if _is_allowed_workspace(p):
                p.mkdir(parents=True, exist_ok=True)
                return p
        except Exception:  # noqa: BLE001
            pass
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_ROOT


def _safe_path(rel: str) -> Path:
    """Résout un chemin RELATIF dans le workspace. Bloque la traversée de répertoire
    ET l'évasion par symlink (un symlink pointant dehors est détecté via .resolve())."""
    ws = _workspace().resolve()
    candidate = (ws / rel)
    resolved = candidate.resolve(strict=False)
    if not str(resolved).startswith(str(ws)):
        raise HTTPException(403, "Accès interdit : chemin hors du workspace")
    current = ws
    try:
        rel_parts = resolved.relative_to(ws).parts
    except ValueError:
        raise HTTPException(403, "Accès interdit : chemin hors du workspace")
    for part in rel_parts:
        current = current / part
        if current.is_symlink():
            target = current.resolve(strict=False)
            if not str(target).startswith(str(ws)):
                raise HTTPException(403, "Accès interdit : symlink vers l'extérieur du workspace")
        if not current.exists():
            break
    return resolved


def _versions_path(file_path: str) -> Path:
    """Dossier de stockage des versions locales d'un fichier (à plat, mono-user)."""
    safe_name = file_path.replace("/", "__").replace("\\", "__")
    return VERSIONS_DIR / safe_name


# ── Détection texte / langage ─────────────────────────────────────────────────

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".html", ".css", ".scss",
    ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".env",
    ".sh", ".bash", ".zsh", ".fish", ".bat", ".cmd", ".ps1",
    ".sql", ".graphql", ".gql", ".xml", ".svg", ".csv",
    ".rs", ".go", ".java", ".kt", ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".lua", ".r", ".swift", ".dart", ".vue", ".svelte",
    ".dockerfile", ".gitignore", ".editorconfig", ".prettierrc",
    ".eslintrc", ".babelrc", ".npmrc", ".lock",
}


def _is_text_file(p: Path) -> bool:
    if p.suffix.lower() in TEXT_EXTENSIONS:
        return True
    if p.name.lower() in {"makefile", "dockerfile", "procfile", "gemfile", "rakefile",
                          "license", "readme"}:
        return True
    mime, _ = mimetypes.guess_type(str(p))
    return mime is not None and mime.startswith("text/")


LANG_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".jsx": "jsx", ".json": "json", ".html": "html",
    ".css": "css", ".scss": "scss", ".md": "markdown", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".sh": "bash", ".bash": "bash",
    ".sql": "sql", ".rs": "rust", ".go": "go", ".java": "java",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
    ".rb": "ruby", ".php": "php", ".lua": "lua", ".swift": "swift",
    ".dart": "dart", ".vue": "vue", ".svelte": "svelte",
    ".xml": "xml", ".svg": "xml", ".graphql": "graphql",
    ".r": "r", ".kt": "kotlin", ".txt": "text",
}


# ── Health + config ───────────────────────────────────────────────────────────

@router.get("/health")
async def code_health():
    ws = _workspace()
    return {"plugin": "spearcode", "status": "ok", "workspace": str(ws), "exists": ws.exists()}


class ConfigUpdate(BaseModel):
    workspace: Optional[str] = None
    font_size: Optional[int] = None


@router.get("/config")
async def get_config():
    return _load_config()


@router.put("/config")
async def update_config(update: ConfigUpdate):
    cfg = _load_config()
    if update.workspace is not None:
        p = Path(update.workspace).resolve()
        if not _is_allowed_workspace(p):
            raise HTTPException(403, "Workspace interdit : hors des racines autorisées "
                                     "(DEV_IDE_WORKSPACE / DEV_IDE_ALLOW_ROOTS).")
        p.mkdir(parents=True, exist_ok=True)
        cfg["workspace"] = str(p)
    if update.font_size is not None:
        cfg["font_size"] = max(8, min(32, update.font_size))
    _save_config(cfg)
    return cfg


# ── Enregistrement des sous-modules (repris de SpearCode) ─────────────────────
# Chacun importe ses helpers d'ici (`from . import …`) et enregistre ses routes
# sur le `router` ci-dessus. À garder en bas : les helpers doivent exister avant.
from . import files      # noqa: E402,F401
from . import versions   # noqa: E402,F401
from . import exec       # noqa: E402,F401
from . import snippets   # noqa: E402,F401
from . import format as _format  # noqa: E402,F401
