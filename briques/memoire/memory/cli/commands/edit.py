import os
import tempfile
import subprocess
import typer
from cli.client import MemoryClient


def edit_cmd(
    node_id: str = typer.Argument(..., help="Node ID to edit"),
):
    client = MemoryClient()
    node = client.get_node(node_id)

    content = f"---\ntitle: {node['title']}\ntype: {node['type']}\n---\n\n{node.get('content_md', '')}"

    editor = os.environ.get("EDITOR", "vim")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = f.name

    try:
        subprocess.call([editor, tmp_path])
        with open(tmp_path, "r") as f:
            edited = f.read()
    finally:
        os.unlink(tmp_path)

    parts = edited.split("---\n", 2)
    if len(parts) >= 3:
        new_title = node["title"]
        for line in parts[1].strip().split("\n"):
            if line.startswith("title:"):
                new_title = line.split(":", 1)[1].strip()
                break
        new_body = parts[2].strip()
    else:
        new_title = node["title"]
        new_body = edited.strip()

    if new_body != node.get("content_md", "") or new_title != node["title"]:
        client.update_node(node_id, title=new_title, content_md=new_body)
        typer.echo(f"Updated [{node['type']}] {new_title}")
    else:
        typer.echo("No changes.")
