"""``verita-verify``: check a signed case file with nothing but the file and a public key.

    verita-verify case-12.json --pubkey keys/verita-pub.pem

Recomputes every leaf from the items in the file, rebuilds the Merkle root, checks the Ed25519
signature over ``verita-case-v1:<case id>:<root>``, and names each item that no longer matches
its recorded leaf. Exit status 0 = valid, 1 = invalid, 2 = unreadable input. No network, no
database, no Verita server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from verita.defend.merkle import MerkleTree, changed_leaves
from verita.defend.signing import load_public_pem, verify_signature

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def main(
    file: Annotated[Path, typer.Argument(help="Signed case-file JSON export")],
    pubkey: Annotated[
        Path | None,
        typer.Option(help="Ed25519 public key PEM (default: the key embedded in the file)"),
    ] = None,
) -> None:
    try:
        export = json.loads(file.read_text(encoding="utf-8"))
        pem = pubkey.read_text(encoding="utf-8") if pubkey else export.get("public_key_pem")
        if not pem:
            typer.echo("No public key: pass --pubkey", err=True)
            raise typer.Exit(2)
        public = load_public_pem(pem)
    except (OSError, ValueError) as exc:
        typer.echo(f"Cannot read input: {exc}", err=True)
        raise typer.Exit(2) from exc

    items = export.get("items", {})
    root = MerkleTree.build(items).root
    changed = changed_leaves(export.get("leaves", {}), items)
    sig = export.get("signature", {})
    case_id = int(export.get("case_id", -1))
    signature_ok = verify_signature(
        public, case_id, export.get("merkle_root", ""), sig.get("value", "")
    )
    root_ok = root == export.get("merkle_root")

    typer.echo(f"case        {case_id}")
    typer.echo(f"key id      {sig.get('key_id', '?')}")
    typer.echo(f"leaves      {len(items)}")
    typer.echo(f"root        {'OK' if root_ok else 'MISMATCH'}  {root}")
    typer.echo(f"signature   {'OK' if signature_ok else 'INVALID'}")
    for name in changed:
        typer.echo(f"changed     {name}")
    valid = signature_ok and root_ok and not changed
    typer.echo("VALID" if valid else "INVALID - this file is not the case file that was signed")
    raise typer.Exit(0 if valid else 1)


if __name__ == "__main__":  # pragma: no cover
    app()
