import typer
from cli.client import MemoryClient


def palace_cmd(
    action: str = typer.Argument("show", help="show / add-wing / add-room / add-drawer"),
    name: str = typer.Option(None, "-n", "--name", help="Name for the new element"),
    wing: str = typer.Option(None, "-w", "--wing", help="Wing name (for add-room / add-drawer)"),
    room: str = typer.Option(None, "-r", "--room", help="Room name (for add-drawer)"),
):
    client = MemoryClient()

    if action == "show":
        tree = client.get_palace()
        wings = tree.get("wings", [])
        if not wings:
            typer.echo("Palace is empty. Add wings with: memory palace add-wing -n <name>")
            return
        for w in wings:
            typer.echo(f"🪟 {w['wing']}  (id: {w['id']})")
            for child in w.get("children", []):
                if child.get("drawer"):
                    typer.echo(f"    └─ 📂 {child['wing']} > {child['room']} > {child['drawer']}  (id: {child['id']})")
                else:
                    typer.echo(f"    ├─ 🚪 {child['room']}  (id: {child['id']})")
                    for gc in child.get("children", []):
                        typer.echo(f"       └─ 📂 {gc['drawer']}  (id: {gc['id']})")

    elif action == "add-wing":
        if not name:
            typer.echo("--name is required")
            raise SystemExit(1)
        result = client.create_wing(name=name)
        typer.echo(f"Wing '{result['wing']}' created. (id: {result['id']})")

    elif action == "add-room":
        if not name or not wing:
            typer.echo("--name and --wing are required")
            raise SystemExit(1)
        result = client.create_room(wing=wing, name=name)
        typer.echo(f"Room '{result['room']}' created in wing '{result['wing']}'. (id: {result['id']})")

    elif action == "add-drawer":
        if not name or not wing or not room:
            typer.echo("--name, --wing, and --room are required")
            raise SystemExit(1)
        result = client.create_drawer(wing=wing, room=room, name=name)
        typer.echo(f"Drawer '{result['drawer']}' created in {result['wing']}>{result['room']}. (id: {result['id']})")

    else:
        typer.echo(f"Unknown action: {action}. Use: show, add-wing, add-room, add-drawer")
