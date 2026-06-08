import typer
from cli.client import MemoryClient


def graph_cmd(
    root: str = typer.Argument(None, help="Root node ID (optional)"),
    depth: int = typer.Option(2, "-d", "--depth", help="Traversal depth"),
):
    client = MemoryClient()
    data = client.get_graph(depth=depth, root=root)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    if not nodes:
        typer.echo("No graph data found.")
        return
    typer.echo(f"Graph: {len(nodes)} nodes, {len(edges)} edges\n")
    for n in nodes:
        typer.echo(f"  [{n['type']}] {n['title']}")
        typer.echo(f"         id: {n['id']}")
    typer.echo()
    for e in edges:
        typer.echo(f"  {e['source'][:8]} → {e['target'][:8]}  [{e['type']}]")
