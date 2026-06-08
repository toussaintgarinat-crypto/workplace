import typer
from cli.client import MemoryClient


def search_cmd(
    query: str,
    type: str = typer.Option(None, "-t", "--type", help="Filter by node type"),
    stage: str = typer.Option(None, "-s", "--stage", help="Filter by IPCRa stage"),
    limit: int = typer.Option(20, "-l", "--limit", help="Number of results"),
):
    client = MemoryClient()
    results = client.search(q=query, type=type, stage=stage, limit=limit)
    if not results:
        typer.echo("No results found.")
        return
    for r in results:
        score = r.get("score", 0)
        typer.echo(f"[{r['type']}] {r['title']}  (score: {score:.3f})")
        preview = r.get("content_md", "")[:160].replace("\n", " ")
        if preview:
            typer.echo(f"  {preview}")
        typer.echo()
