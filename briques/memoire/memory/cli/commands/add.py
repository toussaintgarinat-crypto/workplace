import typer
from cli.client import MemoryClient


def add_cmd(
    title: str,
    type: str = typer.Option("input", "-t", "--type", help="Type: input/projet/casquette/ressource/archive"),
    content: str = typer.Option("", "-c", "--content", help="Markdown content"),
    source_url: str = typer.Option(None, "--source-url", help="Source URL"),
    captured_from: str = typer.Option(None, "--captured-from", help="Source: web/email/voice/note"),
    wing: str = typer.Option(None, "--wing", help="Palace wing"),
    room: str = typer.Option(None, "--room", help="Palace room"),
    drawer: str = typer.Option(None, "--drawer", help="Palace drawer"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated tags"),
):
    client = MemoryClient()
    frontmatter = {}
    if tags:
        frontmatter["tags"] = [t.strip() for t in tags.split(",")]
    location = None
    if wing and room:
        location = {"wing": wing, "room": room}
        if drawer:
            location["drawer"] = drawer
    node = client.create_node(
        type=type,
        title=title,
        content_md=content,
        frontmatter=frontmatter,
        location=location,
        source_url=source_url,
        captured_from=captured_from,
    )
    typer.echo(f"Created [{node['type']}] {node['title']}")
    typer.echo(f"  ID: {node['id']}")
    if node.get("location"):
        loc = node["location"]
        typer.echo(f"  Location: {loc['wing']} > {loc['room']}" + (f" > {loc['drawer']}" if loc.get("drawer") else ""))
