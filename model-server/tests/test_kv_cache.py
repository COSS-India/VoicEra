"""The Parler KV cache has one implementation, and nothing advertises otherwise.

This replaces test_page_table.py, which tested `PageTable` -- part of a paged
attention backend that never ran. runner.py has only ever built both caches with
type="dense", so the paged path, its FlashInfer import and the ~490 lines behind
it were a prototype left switched off, while the root README, the folder README
and that test all described it as the live engine. A well-built test of code
that cannot execute is worse than no test: it reads as coverage.

The property the old file asserted -- never hand one slot to two callers -- now
lives in VirtualMemoryDense, whose state is torch tensors. This suite has only a
torch stub, so that property needs a GPU test rather than this one; what is
pinned here is that the dead backends do not come back and that the claims about
the engine stay true.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGING = ROOT / "tts" / "indic-parler" / "inference" / "paging.py"
RUNNER = ROOT / "tts" / "indic-parler" / "inference" / "runner.py"

pytestmark = pytest.mark.skipif(
    not PAGING.is_file(), reason="indic-parler not in this checkout")

#: Removed with the paged backend. Named individually so re-adding one is a
#: deliberate act with a failing test attached, not a quiet import.
REMOVED = ("PageTable", "VirtualMemoryPaged", "VirtualMemorySDPA", "VirtualMemoryCompare")


def test_only_the_dense_backend_is_defined():
    tree = ast.parse(PAGING.read_text(encoding="utf-8"))
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    back = classes & set(REMOVED)
    assert not back, (
        f"{', '.join(sorted(back))} is defined again in paging.py. These were "
        f"removed because runner.py never selected them; if one is genuinely "
        f"wanted, wire it up in runner.py in the same commit."
    )
    assert "VirtualMemoryDense" in classes, "the backend that actually runs is gone"


def test_the_runner_asks_for_the_backend_that_exists():
    """A `type=` the factory no longer knows would fail at model load, in a
    container, minutes into a first start -- and only for whoever deployed it."""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    asked = {
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "VirtualMemory"
        for kw in node.keywords
        if kw.arg == "type" and isinstance(kw.value, ast.Constant)
    }
    assert asked, "runner.py no longer names a VirtualMemory type explicitly"
    assert asked == {"dense"}, f"runner.py asks for {asked}, which paging.py cannot build"


def test_flashinfer_is_not_a_dependency_of_a_path_that_does_not_use_it():
    """It was imported at module scope for the paged backend alone, which made a
    native wheel an install-time and boot-time requirement of a container that
    never called it. The import failing meant the TTS slot did not start."""
    # Parsed, not grepped. A substring search matches this module's own
    # docstring, which quotes the import it is describing -- the same reason the
    # file/Dockerfile checks below strip comments first. A guard that its own
    # explanation can trip is a guard that gets deleted.
    tree = ast.parse(PAGING.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "flashinfer" not in imported, "paging.py imports flashinfer again"

    folder = PAGING.parent.parent
    for name in ("requirements.txt", "Dockerfile"):
        # Comments stripped first. A prose note explaining why the dependency
        # was dropped is not an installation of it -- counting one would make
        # this guard fail on its own explanation, which is the same defect
        # test_engine_env_surface.py has in the other direction, where a comment
        # naming a variable satisfies a check that it was declared.
        code = "\n".join(
            line.split("#", 1)[0]
            for line in (folder / name).read_text(encoding="utf-8").splitlines()
        )
        assert "flashinfer" not in code, (
            f"{name} installs flashinfer, but nothing imports it any more"
        )


@pytest.mark.parametrize("doc", ["README.md", "tts/indic-parler/README.md"])
def test_the_docs_do_not_advertise_the_engine_it_is_not(doc):
    """Both READMEs called this a paged-KV-cache engine leaning on flashinfer.
    Neither was true, and the wrong description is what sends the next reader to
    the half of the file that never ran."""
    path = ROOT / doc
    if not path.is_file():
        pytest.skip(f"{doc} not in this checkout")
    text = path.read_text(encoding="utf-8").lower()
    for claim in ("paged kv", "paged-kv", "paged attention", "paged-attention", "flashinfer"):
        assert claim not in text, f"{doc} still describes the engine as {claim!r}"
