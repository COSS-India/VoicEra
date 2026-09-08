"""Every knob a model reads must be declared where the model is deployed.

An undeclared environment variable does not fail. The container starts, the
model serves, and the code quietly takes whatever fallback is written into its
own source -- which is the upstream author's development default, not the value
the deployment was tuned to.

This is not hypothetical, and the cost was not small. `CORE_CHUNK_SECS` and
`CORE_RIGHT_SECS` were read by `stt/indic-transcribe/app.py` and declared
nowhere in this slot, so both fell back to NeMo's own geometry: a 1.0 s chunk
and 0.5 s right context, which NeMo floors to a theoretical per-word latency of
1.44 s. Upstream ships 0.24 / 0.16 -- 0.40 s -- and every latency number it
publishes was measured there. The slot ran the model at 3.6x the intended
latency for as long as it was deployed. Nothing logged it, nothing was wrong
with the transcript, and the only symptom was a demo that felt sluggish.

The general shape is worse than the specific bug: a fallback in source and a
default in compose are two copies of one number, and nothing makes them agree.
Declaring every variable is what makes the deployment the single place the
value lives.

Upstream added the same gate to its own `verify.sh` after the same class of bug
(commit f271443, six undeclared variables). This is that gate, for the slot.

**What this cannot see, and it has already bitten once.** It finds variables the
model's OWN code reads. A variable consumed by a dependency is invisible to it:
`VLLM_LOGGING_LEVEL` is read by vLLM, never by orpheus_server, so this file
called the folder clean while the image's baked-in WARNING hid the entire boot
sequence -- and a first load of a 7.6 GB checkpoint became indistinguishable
from a hang. Detecting those in general is not tractable; the mitigation is to
read a vendored image's own Dockerfile ENV lines when adding a model, and to
treat anything set there that the deployment does not restate as a decision
somebody else made for you.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SLOTS = ("stt", "tts", "llm")

#: Reads that are not deployment configuration.
#: PORT is set by the slot contract; the HF_* pair is Hugging Face's own and is
#: declared at the slot level for every model at once.
EXEMPT = {"PORT", "HF_HOME", "HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "PYTHONPATH",
          "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"}

#: Known gaps, by model folder. Each entry is a variable whose value the
#: deployment cannot currently set -- the same defect as the geometry one above,
#: in a model nobody has audited yet. They are listed rather than ignored so the
#: list is a work item and not an absence, and so a NEW undeclared variable
#: fails this test instead of joining a silent majority.
#:
#: Shrink this. Do not grow it.
KNOWN_UNDECLARED = {
    "indic-conformer": {"REALTIME_INTERIM_MS", "REALTIME_MAX_SESSIONS"},
    "indic-mio": {
        # Not declared on purpose. The Dockerfile CMD is
        # `--port ${PORT:-${MIO_PORT:-8002}}`, and the slot always sets PORT, so
        # MIO_PORT can never win. Declaring it would add a second knob for the
        # port that silently does nothing -- the ASR_DEFAULT_LANG mistake, which
        # indic-nemotron's overlay documents at length. PORT is the knob.
        "MIO_PORT",
        "MIO_DECODE_CONCURRENCY", "MIO_FLUSH_TOKENS", "MIO_FRAME_SAMPLES",
        "MIO_LLM_TIMEOUT", "MIO_LOG_LEVEL", "MIO_LOOKAHEAD_TOKENS",
        "MIO_MAX_TEXT_LENGTH", "MIO_MAX_TOKENS", "MIO_REPETITION_PENALTY",
        "MIO_TEMPERATURE", "MIO_TOKEN_RATE_HZ", "MIO_TOP_P",
    },
}

READS = re.compile(
    r'(?:os\.getenv|os\.environ\.get|_env_int|_env_float|_env_bool)\('
    r'\s*["\']([A-Z][A-Z0-9_]*)["\']'
)
#: A variable name used as a dict key, for the other way a model reads its
#: environment: a table mapping env names to config paths, walked in a loop.
#: orpheus reads 27 of its 29 variables that way, and a detector that only
#: understood os.getenv() calls found two and pronounced the folder clean --
#: which is precisely the false confidence this file exists to prevent.
ENV_LIKE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
#: A name mentioned anywhere in a compose file or Dockerfile counts as declared.
#: Deliberately loose about syntax; deliberately strict about which files.
#:
#: `.env.example` is NOT one of them, and the difference is the whole bug.
#: Compose passes a variable into a container only if the service's
#: `environment:` block names it. A line in `.env` that no compose file
#: references is inert -- the operator sets it, restarts, and nothing changes.
#: Counting the example file here would have let this test pass on a variable
#: that is documented and unsettable, which is worse than one that is neither.
#: That documentation is real and required, but it is `test_env_example.py`'s
#: job; this test is about what actually reaches the process.
MENTIONS = re.compile(r'\b([A-Z][A-Z0-9_]{2,})\b')


def model_folders() -> list[Path]:
    """Found by walking, so a model folder is covered the moment it is copied in.

    A list would have to be edited by the same person who forgot to declare the
    variable.
    """
    # rglob, not glob: orpheus keeps its code under src/, so a top-level check
    # skipped the folder entirely -- and it was the one shipping a GPU
    # reservation sized for a dedicated card.
    return sorted(f for slot in SLOTS for f in (ROOT / slot).glob("*")
                  if f.is_dir() and any(f.rglob("*.py")))


def reads(folder: Path) -> set[str]:
    import ast

    found: set[str] = set()
    for f in folder.rglob("*.py"):
        # Benchmarks, conversion tools and the vendored NeMo patch are not the
        # served application; they run by hand with arguments.
        if {"bench", "tools", "tests", "nemo_patch"} & set(f.parts):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        found |= set(READS.findall(text))
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and ENV_LIKE.match(key.value)):
                    found.add(key.value)
    return found - EXEMPT


def _compose_declared(path: Path) -> set[str]:
    """Environment keys a compose file actually passes to a container.

    Parsed, not scanned. This used to regex the file's whole text, so a COMMENT
    counted as a declaration -- and these files are heavily commented, usually
    about the very variables in question. Deleting the real
    `CORE_CHUNK_SECS: "${CORE_CHUNK_SECS:-0.24}"` line while leaving the prose
    above it that names the variable kept this test green, with the variable
    genuinely unset in the container. That is the exact defect the file was
    written for, walking through its own guard.

    Reads `environment:` in both spellings Compose accepts: a mapping, and a
    list of `KEY=value` strings.
    """
    names: set[str] = set()
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except yaml.YAMLError:
        return names
    for svc in (doc.get("services") or {}).values():
        if not isinstance(svc, dict):
            continue
        env = svc.get("environment")
        if isinstance(env, dict):
            names |= {str(k) for k in env}
        elif isinstance(env, list):
            names |= {str(item).split("=", 1)[0].strip() for item in env}
    return names


def _dockerfile_declared(path: Path) -> set[str]:
    """ENV/ARG names in a Dockerfile, with comments stripped.

    Same reasoning as above, plus MENTIONS matched Dockerfile keywords: RUN, ENV,
    COPY, FROM, WORKDIR, CMD and EXPOSE all look like environment variables to a
    `[A-Z][A-Z0-9_]{2,}` pattern, so seven names were "declared" in every image.
    """
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        head, _, rest = line.partition(" ")
        if head.upper() not in {"ENV", "ARG"} or not rest:
            continue
        for part in rest.split():
            key = part.split("=", 1)[0].strip()
            if ENV_LIKE.match(key):
                names.add(key)
    return names


def declared(folder: Path) -> set[str]:
    names: set[str] = set()
    for f in list(folder.glob("compose*.yml")) + list(ROOT.glob("compose*.yml")):
        if f.is_file():
            names |= _compose_declared(f)
    for f in folder.glob("Dockerfile*"):
        if f.is_file():
            names |= _dockerfile_declared(f)
    return names


@pytest.mark.parametrize("folder", model_folders(), ids=lambda f: f.name)
def test_every_variable_a_model_reads_can_be_set_where_it_is_deployed(folder):
    missing = reads(folder) - declared(folder) - KNOWN_UNDECLARED.get(folder.name, set())
    assert not missing, (
        f"{folder.name} reads {sorted(missing)} but no compose file or Dockerfile "
        f"passes them into the container. Each one silently takes the fallback "
        f"written in its own source, which is the upstream author's default and "
        f"not necessarily this deployment's -- and setting it in .env will not "
        f"help, because nothing references it. Declare them in "
        f"{folder.name}/compose.extra.yml, then document them in .env.example."
    )


def test_the_known_gaps_list_has_not_grown():
    """The allowlist above is a debt register, and a register nobody reconciles
    is just a way of not looking. If a model has been fixed, delete its entry --
    this fails when an entry no longer describes a real gap, so the list cannot
    quietly rot into a permanent exemption."""
    by_name = {f.name: f for f in model_folders()}
    for name, allowed in KNOWN_UNDECLARED.items():
        folder = by_name.get(name)
        if folder is None:
            pytest.skip(f"{name} not present in this checkout")
        stale = allowed - (reads(folder) - declared(folder))
        assert not stale, (
            f"{name}: {sorted(stale)} no longer undeclared -- remove from "
            f"KNOWN_UNDECLARED so the list keeps meaning something."
        )


def test_the_streaming_geometry_is_declared_and_is_the_measured_one():
    """The specific regression, pinned by value rather than by presence.

    chunk + right IS the per-word latency floor -- the number every published
    measurement for this model was taken at. Declaring the variables but
    declaring them wrong would pass the test above and reintroduce the bug, so
    the values are asserted, not just their existence.
    """
    overlay = ROOT / "stt" / "indic-transcribe" / "compose.extra.yml"
    if not overlay.is_file():
        pytest.skip("indic-transcribe not present in this checkout")
    text = overlay.read_text(encoding="utf-8")
    for var, want in (("CORE_CHUNK_SECS", "0.24"), ("CORE_RIGHT_SECS", "0.16"),
                      ("CORE_LEFT_SECS", "10.0")):
        m = re.search(rf'{var}:\s*"\$\{{{var}:-([^}}]*)\}}"', text)
        assert m, f"{var} is not declared with an overridable default"
        assert m.group(1) == want, (
            f"{var} defaults to {m.group(1)}, not the {want} every latency "
            f"measurement for this checkpoint was taken at. chunk + right is "
            f"the per-word latency floor: 0.24 + 0.16 reads 0.40 s, NeMo's "
            f"1.0 + 0.5 reads 1.44 s, and neither errors."
        )
