#!/usr/bin/env python3
import typer
from cli.client import MemoryClient
from cli.commands.add import add_cmd
from cli.commands.recall import recall_cmd
from cli.commands.search import search_cmd
from cli.commands.list import list_cmd
from cli.commands.move import move_cmd
from cli.commands.link import link_cmd
from cli.commands.graph import graph_cmd
from cli.commands.palace import palace_cmd
from cli.commands.gardien import gardien_cmd
from cli.commands.export import export_cmd
from cli.commands.open import open_cmd
from cli.commands.edit import edit_cmd

app = typer.Typer(
    name="memory",
    help="Memory — Personal augmented memory system",
    no_args_is_help=True,
)


@app.command()
def init(
    name: str = typer.Option("My Memory", "-n", "--name", help="Space name"),
    description: str = typer.Option("", "-d", "--desc", help="Space description"),
    email: str = typer.Option(None, "-e", "--email", help="Register with email"),
    password: str = typer.Option(None, "-p", "--password", help="Password"),
):
    client = MemoryClient()
    if email and password:
        client.register(email, password)
        typer.echo(f"Registered: {email}")
        client.login(email, password)
        typer.echo(f"Logged in: {email}")
    space = client.init_space(name=name, description=description)
    typer.echo(f"Space initialized: {space['name']} (id: {space['id']})")
    typer.echo("You can now use: memory add, memory recall, ...")


@app.command()
def login(
    email: str = typer.Argument(..., help="Email"),
    password: str = typer.Argument(..., help="Password"),
):
    client = MemoryClient()
    data = client.login(email, password)
    typer.echo(f"Logged in as {email} (token: {data['access_token'][:20]}...)")


@app.command()
def logout():
    MemoryClient().logout()


@app.command()
def config(
    action: str = typer.Argument("show", help="show / set-space"),
    space_id: str = typer.Option(None, "--space-id", "-s", help="Space UUID (for set-space)"),
):
    client = MemoryClient()
    if action == "show":
        spaces = client.list_spaces()
        typer.echo("Spaces:")
        for s in spaces:
            marker = " (current)" if str(s["id"]) == client.config.get("space_id") else ""
            typer.echo(f"  [{s['id']}] {s['name']}{marker}")
    elif action == "set-space":
        if not space_id:
            typer.echo("--space-id is required")
            raise SystemExit(1)
        client.set_space(space_id)
        typer.echo(f"Space set to: {space_id}")


@app.command()
def add(
    title: str = typer.Argument(..., help="Title of the memory"),
    type: str = typer.Option("input", "-t", "--type", help="Type: input/projet/casquette/ressource/archive"),
    content: str = typer.Option("", "-c", "--content", help="Markdown content"),
    source_url: str = typer.Option(None, "--source-url", help="Source URL"),
    captured_from: str = typer.Option(None, "--captured-from", help="Source: web/email/voice/note"),
    wing: str = typer.Option(None, "--wing", help="Palace wing"),
    room: str = typer.Option(None, "--room", help="Palace room"),
    drawer: str = typer.Option(None, "--drawer", help="Palace drawer"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated tags"),
):
    add_cmd(title, type=type, content=content, source_url=source_url,
            captured_from=captured_from, wing=wing, room=room, drawer=drawer, tags=tags)


@app.command()
def recall(
    query: str = typer.Argument(..., help="Semantic search query"),
    limit: int = typer.Option(10, "-l", "--limit", help="Number of results"),
    stage: str = typer.Option(None, "-s", "--stage", help="Filter by IPCRa stage"),
    type: str = typer.Option(None, "-t", "--type", help="Filter by node type"),
):
    recall_cmd(query, limit=limit, stage=stage, type=type)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    type: str = typer.Option(None, "-t", "--type", help="Filter by node type"),
    stage: str = typer.Option(None, "-s", "--stage", help="Filter by IPCRa stage"),
    limit: int = typer.Option(20, "-l", "--limit", help="Number of results"),
):
    search_cmd(query, type=type, stage=stage, limit=limit)


@app.command()
def list(
    type: str = typer.Option(None, "-t", "--type", help="Filter by node type"),
    stage: str = typer.Option(None, "-s", "--stage", help="Filter by IPCRa stage"),
    status: str = typer.Option("active", "--status", help="Filter by status"),
    wing: str = typer.Option(None, "--wing", help="Filter by palace wing"),
    room: str = typer.Option(None, "--room", help="Filter by palace room"),
    limit: int = typer.Option(50, "-l", "--limit", help="Max results"),
):
    list_cmd(type=type, stage=stage, status=status, wing=wing, room=room, limit=limit)


@app.command()
def open(
    node_id: str = typer.Argument(..., help="Node ID to open"),
):
    open_cmd(node_id)


@app.command()
def edit(
    node_id: str = typer.Argument(..., help="Node ID to edit"),
):
    edit_cmd(node_id)


@app.command()
def move(
    node_id: str = typer.Argument(..., help="Node ID"),
    stage: str = typer.Option(..., "--to", "-t", help="Target IPCRa stage"),
    reason: str = typer.Option(None, "--reason", "-r", help="Reason for transition"),
):
    move_cmd(node_id, stage=stage, reason=reason)


@app.command()
def link(
    source_id: str = typer.Argument(..., help="Source node ID"),
    target_id: str = typer.Argument(..., help="Target node ID"),
    type: str = typer.Option("related", "-t", "--type", help="Edge type: related/cause/part_of/reference/sequence"),
    weight: float = typer.Option(1.0, "-w", "--weight"),
):
    link_cmd(source_id, target_id, type=type, weight=weight)


@app.command()
def graph(
    root: str = typer.Argument(None, help="Root node ID"),
    depth: int = typer.Option(2, "-d", "--depth", help="Traversal depth"),
):
    graph_cmd(root, depth=depth)


@app.command()
def palace(
    action: str = typer.Argument("show", help="show / add-wing / add-room / add-drawer"),
    name: str = typer.Option(None, "-n", "--name", help="Name"),
    wing: str = typer.Option(None, "-w", "--wing", help="Wing name"),
    room: str = typer.Option(None, "-r", "--room", help="Room name"),
):
    palace_cmd(action, name=name, wing=wing, room=room)


@app.command()
def gardien(
    action: str = typer.Argument("status", help="status / run / suggestions / accept / reject / config / log"),
    id: str = typer.Option(None, "--id", "-i", help="Suggestion ID"),
    mode: str = typer.Option(None, "--mode", "-m", help="Mode: propose/auto/off"),
    interval: int = typer.Option(None, "--interval", help="Interval in minutes"),
):
    gardien_cmd(action, id=id, mode=mode, interval=interval)


@app.command()
def touch(
    node_id: str = typer.Argument(..., help="Node ID to reinforce"),
):
    client = MemoryClient()
    result = client.touch_node(node_id)
    typer.echo(f"Touched: access_count={result['access_count']}")


@app.command()
def aging():
    client = MemoryClient()
    nodes = client.get_aging_nodes()
    if not nodes:
        typer.echo("No aging nodes.")
        return
    typer.echo(f"Aging nodes (ready for tier demotion):\n")
    for n in nodes:
        typer.echo(f"  [{n['storage_tier']}] {n['title']}")


@app.command()
def stats():
    client = MemoryClient()
    s = client.stats()
    typer.echo(f"Total nodes:    {s['total']}")
    typer.echo(f"\nBy type:")
    for t, c in sorted(s["types"].items()):
        typer.echo(f"  {t:>12}: {c}")
    typer.echo(f"\nBy stage:")
    for st, c in sorted(s["stages"].items()):
        typer.echo(f"  {st:>12}: {c}")
    typer.echo(f"\nBy tier:")
    for t, c in sorted(s["tiers"].items()):
        typer.echo(f"  {t:>12}: {c}")


@app.command()
def demote():
    client = MemoryClient()
    result = client.run_tiers()
    typer.echo(result.get("detail", "Tier demotion completed"))


@app.command()
def export(
    format: str = typer.Option("json", "-f", "--format", help="json or markdown"),
    output: str = typer.Option(None, "-o", "--output", help="Output file path"),
):
    export_cmd(format=format, output=output)


if __name__ == "__main__":
    app()
