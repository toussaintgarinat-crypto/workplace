import typer
from cli.client import MemoryClient


def move_cmd(
    node_id: str,
    stage: str = typer.Option(..., "--to", "-t", help="Target IPCRa stage: input/projet/casquette/ressource/archive"),
    reason: str = typer.Option(None, "--reason", "-r", help="Reason for the transition"),
):
    client = MemoryClient()
    valid_stages = {"input", "projet", "casquette", "ressource", "archive"}
    if stage not in valid_stages:
        typer.echo(f"Invalid stage: {stage}. Valid: {', '.join(valid_stages)}")
        raise SystemExit(1)
    node = client.update_stage(node_id, stage, reason)
    typer.echo(f"Moved [{node['type']}] {node['title']} → stage: {node['ipcra_stage']}")
