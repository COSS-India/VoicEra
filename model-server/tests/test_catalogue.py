"""The /models catalogue.

Guards the two ways this can go wrong quietly: a malformed models.yaml, and
/v1/models drifting into advertising something a caller would get a 503 from.
"""
from pathlib import Path

import pytest
import yaml
from app import catalogue

# Anchored to this file, not to catalogue.CATALOGUE_PATH: that now resolves to
# whichever copy exists (image or checkout), so deriving the repo root from it
# walks a different number of levels depending on how the gateway was started.
CATALOGUE = Path(__file__).resolve().parent.parent / "models.yaml"


def test_catalogue_file_is_valid():
    raw = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    assert set(raw) <= set(catalogue.KINDS), \
        f"unexpected top-level keys: {set(raw) - set(catalogue.KINDS)}"
    for kind in catalogue.KINDS:
        for entry in raw.get(kind) or []:
            assert entry.get("id"), f"{kind} entry with no id"
            assert entry.get("status") in {"ready", "planned"}, f"{entry['id']}: bad status"


def test_ids_are_unique_within_a_kind():
    raw = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    for kind in catalogue.KINDS:
        ids = [e["id"] for e in raw.get(kind) or []]
        assert len(ids) == len(set(ids)), f"duplicate ids in {kind}: {ids}"


def test_load_flattens_and_tags_kind():
    models = catalogue.load(CATALOGUE)
    assert models, "catalogue loaded empty"
    assert all(m["kind"] in catalogue.KINDS for m in models)
    ready = [m["id"] for m in models if m["status"] == "ready"]
    assert "indic-conformer" in ready
    assert "indic-parler" in ready


def test_missing_catalogue_is_not_fatal(tmp_path):
    # The gateway must keep routing even if it cannot describe itself.
    assert catalogue.load(tmp_path / "nope.yaml") == []


@pytest.mark.parametrize("kind", catalogue.KINDS)
def test_every_deployable_model_has_a_folder(kind):
    """A model marked ready must be startable, or `ready` is a lie.

    Compose builds <kind>/<id>/, so that folder and a Dockerfile in it are the
    whole requirement -- there is no per-model wiring left to forget.
    """
    root = CATALOGUE.parent
    raw = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    for entry in raw.get(kind) or []:
        if entry["status"] != "ready":
            continue
        folder = root / kind / entry["id"]
        assert folder.is_dir(), \
            f"{entry['id']} is marked ready but {kind}/{entry['id']}/ is missing"
        assert (folder / "Dockerfile").is_file(), \
            f"{kind}/{entry['id']}/ has no Dockerfile, so Compose cannot build it"


@pytest.mark.parametrize("kind", catalogue.KINDS)
def test_every_model_folder_is_in_the_catalogue(kind):
    """The other direction: a folder nobody catalogued is invisible at /models."""
    root = CATALOGUE.parent / kind
    if not root.is_dir():
        return
    raw = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    known = {e["id"] for e in raw.get(kind) or []}
    folders = (p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
    for folder in sorted(folders):
        assert folder.name in known, \
            f"{kind}/{folder.name}/ exists but is not listed in models.yaml"


def test_slot_profiles_are_slot_names_not_model_names():
    """Profiles answer 'is this slot on'; <KIND>_MODEL answers 'which model'.

    If a profile were ever named after a model again, switching models would
    silently start nothing.
    """
    compose = yaml.safe_load(
        (CATALOGUE.parent / "compose.model-server.yml").read_text(encoding="utf-8")
    )
    for name, svc in compose["services"].items():
        for profile in svc.get("profiles", []):
            assert profile == name, (
                f"service {name} has profile {profile!r}; profiles must be the slot name"
            )


# ------------------------------------------------- where the catalogue lives

def test_a_catalogue_that_is_not_a_mapping_is_survivable(tmp_path):
    """Valid YAML that is not a mapping of kinds must not take /models down.

    This is not hypothetical. `gateway/app/models.yaml` was committed as a
    symlink to an absolute path on one developer's machine. On Linux it resolved;
    on a Windows checkout git materialised it as a 62-byte text file containing
    its own target, which is valid YAML -- it parses to a string. `raw.get(kind)`
    on a str raises AttributeError, which the loader's except clause does not
    catch, so the endpoint answered 500 instead of the empty list its own
    docstring promises.
    """
    for content in ("/home/someone/models.yaml", "- just\n- a list\n", "42"):
        bad = tmp_path / "bad.yaml"
        bad.write_text(content, encoding="utf-8")
        assert catalogue.load(bad) == [], f"{content!r} was not survived"


def test_the_catalogue_is_found_from_a_checkout_as_well_as_an_image():
    """Two ways this gateway runs, one of which has no copy beside the module.

    The image copies models.yaml next to the app; `model-server/run/` starts
    uvicorn straight from the checkout, where only the root copy exists. Finding
    both is what makes the symlink unnecessary.
    """
    resolved = catalogue.CATALOGUE_PATH
    assert resolved.is_file(), f"no catalogue found at {resolved}"
    assert catalogue.load(), "the catalogue resolved but loaded empty"


def test_no_symlinked_catalogue_is_committed():
    """A symlink here works on the machine that made it and nowhere else."""
    stray = catalogue.CATALOGUE_PATH.parent / "models.yaml"
    root = CATALOGUE
    if stray.resolve() == root.resolve():
        return                      # they are the same file; nothing to check
    assert not stray.exists(), (
        f"{stray} shadows {root}. The Dockerfile already copies the real "
        f"catalogue into place and Compose bind-mounts it; a second copy here "
        f"only differs from the first."
    )
