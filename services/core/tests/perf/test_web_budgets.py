"""The web pages' bundle-size budget (scripts/ci/web_budgets.py).

Each page's first-load JavaScript, gzipped as it is served: Next's root chunks plus
every chunk its layouts and page load (from the build's client reference manifests),
each chunk counted once.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[4]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "ci" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


web = _load("web_budgets")


def _chunk(next_dir: Path, name: str, size: int) -> int:
    path = next_dir / "static" / "chunks" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (name * (size // len(name) + 1))[:size].encode()
    path.write_bytes(data)
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def _page(next_dir: Path, route: str, entries: dict[str, list[str]]) -> None:
    manifest = next_dir / "server" / "app" / route.lstrip("/") / "page_client-reference-manifest.js"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "clientModules": {},
        "entryJSFiles": {k: [f"static/chunks/{c}" for c in v] for k, v in entries.items()},
    }
    manifest.write_text(
        "globalThis.__RSC_MANIFEST = globalThis.__RSC_MANIFEST || {};\n"
        f'globalThis.__RSC_MANIFEST["{route}/page"] = {json.dumps(body)};\n'
    )


def test_a_page_counts_root_chunks_and_its_own_once(tmp_path: Path) -> None:
    nxt = tmp_path / ".next"
    root = _chunk(nxt, "root.js", 5000)
    layout = _chunk(nxt, "layout.js", 3000)
    board = _chunk(nxt, "board.js", 9000)
    (nxt / "build-manifest.json").write_text(
        json.dumps({"rootMainFiles": ["static/chunks/root.js"], "polyfillFiles": []})
    )
    _page(
        nxt,
        "/(app)/w/[id]/board",
        {
            "[project]/app/layout": ["layout.js"],
            "[project]/app/w/board/page": ["board.js", "layout.js"],
        },
    )
    _page(nxt, "/(auth)/login", {"[project]/app/layout": ["layout.js"]})
    metrics = web.measure(nxt)
    assert metrics["web.page./w/[id]/board.gzip_kB"] == {
        "value": round((root + layout + board) / 1024, 1),
        "unit": "kB",
    }
    assert metrics["web.page./login.gzip_kB"]["value"] == round((root + layout) / 1024, 1)
    assert metrics["web.all_js.gzip_kB"]["value"] == round((root + layout + board) / 1024, 1)


def test_a_missing_build_is_an_error(tmp_path: Path) -> None:
    try:
        web.measure(tmp_path / "nothing")
    except SystemExit as error:
        assert "next build" in str(error)
    else:
        raise AssertionError("no error for a missing build")


def test_the_real_build_if_there_is_one() -> None:
    nxt = REPO / "apps" / "web" / ".next"
    if not (nxt / "build-manifest.json").is_file():
        return
    metrics = web.measure(nxt)
    assert "web.page./w/[id]/chats.gzip_kB" in metrics, sorted(metrics)[:10]
    assert all(v["value"] > 0 for v in metrics.values())
