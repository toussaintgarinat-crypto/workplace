import typer
from cli.client import MemoryClient


def recall_cmd(
    query: str,
    limit: int = typer.Option(10, "-l", "--limit", help="Number of results"),
    stage: str = typer.Option(None, "-s", "--stage", help="Filter by IPCRa stage"),
    type: str = typer.Option(None, "-t", "--type", help="Filter by node type"),
):
    client = MemoryClient()
    results = client.semantic_search(query=query, limit=limit, stage_filter=stage, type_filter=type)
    if not results:
        typer.echo("No results found.")
        return
    for r in results:
        score = r.get("score", 0)
        bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        typer.echo(f"[{r['type']}] {r['title']}")
        typer.echo(f"  Score: {score:.3f} {bar}")
        preview = r.get("content_md", "")[:120].replace("\n", " ")
        if preview:
            typer.echo(f"  {preview}...")
        typer.echo()
