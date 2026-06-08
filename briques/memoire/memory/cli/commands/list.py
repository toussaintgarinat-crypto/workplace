import typer
from cli.client import MemoryClient


def list_cmd(
    type: str = typer.Option(None, "-t", "--type", help="Filter by node type"),
    stage: str = typer.Option(None, "-s", "--stage", help="Filter by IPCRa stage"),
    status: str = typer.Option("active", "--status", help="Filter by status"),
    wing: str = typer.Option(None, "--wing", help="Filter by palace wing"),
    room: str = typer.Option(None, "--room", help="Filter by palace room"),
    limit: int = typer.Option(50, "-l", "--limit", help="Max results"),
):
    client = MemoryClient()
    nodes = client.list_nodes(type=type, stage=stage, status=status, wing=wing, room=room, limit=limit)
    if not nodes:
        typer.echo("No nodes found.")
        return
    typer.echo(f"Found {len(nodes)} node(s):\n")
    for n in nodes:
        loc = ""
        if n.get("location"):
            loc = f" @ {n['location']['wing']}>{n['location']['room']}"
        typer.echo(f"  [{n['type']:>10}] {n['title']}")
        tier = n.get('storage_tier', 'hot')
        typer.echo(f"         stage={n['ipcra_stage']}  tier={tier}  id={n['id']}{loc}")
