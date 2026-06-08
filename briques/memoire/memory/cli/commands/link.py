import typer
from cli.client import MemoryClient


def link_cmd(
    source_id: str = typer.Argument(..., help="Source node ID"),
    target_id: str = typer.Argument(..., help="Target node ID"),
    type: str = typer.Option("related", "-t", "--type", help="Edge type: related/cause/part_of/reference/sequence"),
    weight: float = typer.Option(1.0, "-w", "--weight"),
):
    client = MemoryClient()
    edge = client.create_edge(source_id=source_id, target_id=target_id, type=type, weight=weight)
    typer.echo(f"Linked {source_id} → {target_id} [{type}]")
    typer.echo(f"  Edge ID: {edge['id']}")
