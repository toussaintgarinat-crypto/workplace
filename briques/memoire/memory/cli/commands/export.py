import typer
from cli.client import MemoryClient


def export_cmd(
    format: str = typer.Option("json", "-f", "--format", help="Export format: json or markdown"),
    output: str = typer.Option(None, "-o", "--output", help="Output file path (default: stdout)"),
):
    client = MemoryClient()
    data = client.export(format=format)
    if output:
        with open(output, "w") as f:
            if isinstance(data, dict):
                import json
                json.dump(data, f, indent=2, default=str)
            else:
                f.write(data)
        typer.echo(f"Exported to {output}")
    else:
        if isinstance(data, dict):
            import json
            typer.echo(json.dumps(data, indent=2, default=str))
        else:
            typer.echo(data)
