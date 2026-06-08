import webbrowser
import typer
from cli.client import MemoryClient


def open_cmd(
    node_id: str = typer.Argument(..., help="Node ID to open in browser"),
):
    client = MemoryClient()
    node = client.get_node(node_id)
    url = f"http://localhost:5173/memory/note/{node_id}"
    typer.echo(f"Opening: {node['title']}")
    typer.echo(f"  URL: {url}")
    webbrowser.open(url)
