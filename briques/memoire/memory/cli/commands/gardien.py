import typer
from cli.client import MemoryClient


def gardien_cmd(
    action: str = typer.Argument("status", help="status / run / suggestions / accept / reject / config / log"),
    id: str = typer.Option(None, "--id", "-i", help="Suggestion ID (for accept/reject)"),
    mode: str = typer.Option(None, "--mode", "-m", help="Gardien mode: propose/auto/off"),
    interval: int = typer.Option(None, "--interval", help="Interval in minutes"),
):
    client = MemoryClient()

    if action == "status":
        cfg = client.gardien_config()
        typer.echo("Gardien Configuration:")
        typer.echo(f"  Mode:     {cfg.get('mode', '?')}")
        typer.echo(f"  Interval: {cfg.get('interval_minutes', '?')} min")
        typer.echo(f"  Summarize:  {cfg.get('auto_summarize', False)}")
        typer.echo(f"  Merge:      {cfg.get('auto_merge', False)}")
        typer.echo(f"  Infer:      {cfg.get('auto_infer', False)}")
        typer.echo(f"  Suggest IPCRa: {cfg.get('auto_suggest_ipcra', False)}")
        typer.echo(f"  Auto Archive: {cfg.get('auto_archive', False)}")

    elif action == "run":
        result = client.gardien_run()
        typer.echo(f"Gardien run: {result.get('detail', 'OK')}")
        if result.get("results"):
            for r in result["results"]:
                typer.echo(f"  - {r}")

    elif action == "suggestions":
        suggestions = client.gardien_suggestions()
        if not suggestions:
            typer.echo("No pending suggestions.")
            return
        for s in suggestions:
            typer.echo(f"[{s['status']}] {s['action']}  (id: {s['id']})")
            if s.get("details"):
                typer.echo(f"    Details: {s['details']}")
            if s.get("node_id"):
                typer.echo(f"    Node: {s['node_id']}")
            typer.echo()

    elif action == "accept":
        if not id:
            typer.echo("--id <suggestion_id> is required")
            raise SystemExit(1)
        result = client.gardien_accept(id)
        typer.echo(f"Accepted: {result.get('detail', 'OK')}")

    elif action == "reject":
        if not id:
            typer.echo("--id <suggestion_id> is required")
            raise SystemExit(1)
        result = client.gardien_reject(id)
        typer.echo(f"Rejected: {result.get('detail', 'OK')}")

    elif action == "config":
        cfg = client.gardien_config()
        updates = {}
        if mode:
            updates["mode"] = mode
        if interval is not None:
            updates["interval_minutes"] = interval
        if updates:
            cfg.update(updates)
            result = client.gardien_set_config(cfg)
            typer.echo(f"Config updated: mode={result['mode']}, interval={result['interval_minutes']}min")
        else:
            typer.echo(f"Current config: mode={cfg['mode']}, interval={cfg['interval_minutes']}min")

    elif action == "log":
        logs = client.gardien_log()
        if not logs:
            typer.echo("No gardien log entries.")
            return
        for entry in logs:
            typer.echo(f"[{entry['status']:>8}] {entry['action']}  ({entry['created_at'][:19]})")
            if entry.get("node_id"):
                typer.echo(f"         Node: {entry['node_id']}")

    else:
        typer.echo(f"Unknown action: {action}")
        typer.echo("Valid actions: status, run, suggestions, accept, reject, config, log")
