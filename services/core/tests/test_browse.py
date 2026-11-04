"""The folder picker lists folder names only, and never offers private ones."""

from pathlib import Path
from typing import Any

from test_library import env  # noqa: F401 - fixture


def test_browse_lists_folders_and_hides_private_ones(env: Any, tmp_path: Path) -> None:  # noqa: F811
    client, core, _runner, hermes_home = env
    home = core.engine.settings.host_home
    (home / "Documents" / "reports").mkdir(parents=True)
    (home / "Documents" / "notes.txt").write_text("secret words")
    (home / ".ssh").mkdir()
    (home / ".hidden").mkdir()
    listing = client.get("/machine/folders").json()
    assert Path(listing["path"]) == home.resolve()
    names = [f["name"] for f in listing["folders"]]
    # Hermes's home and hidden folders never show; files never show.
    assert "Documents" in names and ".ssh" not in names and ".hidden" not in names
    assert ".hermes" not in names
    assert any(p["name"] == "Documents" for p in listing["places"])

    docs = client.get("/machine/folders", params={"path": str(home / "Documents")}).json()
    assert [f["name"] for f in docs["folders"]] == ["reports"]
    assert docs["folders"][0]["canAdd"] is True
    assert Path(docs["parent"]) == home.resolve()
    assert "secret words" not in str(docs)

    # Private folders can't be opened; bad paths are refused.
    assert client.get("/machine/folders", params={"path": str(home / ".ssh")}).status_code == 403
    assert client.get("/machine/folders", params={"path": str(hermes_home)}).status_code == 403
    assert client.get("/machine/folders", params={"path": str(core.layout.root)}).status_code == 403
    assert client.get("/machine/folders", params={"path": "relative/x"}).status_code == 400
    assert client.get("/machine/folders", params={"path": "/nope/nothing"}).status_code == 404
    # The home folder holds private ones, so it can be opened but not added itself.
    assert client.get("/machine/folders", params={"path": "/"}).json()["parent"] is None
    root_entry = next(p for p in listing["places"] if p["name"] == "Home")
    assert root_entry["canAdd"] is False
