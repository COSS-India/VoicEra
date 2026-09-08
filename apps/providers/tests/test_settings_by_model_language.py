"""Accuracy checks for capabilities dump across STT/TTS providers."""

from __future__ import annotations

from apps.providers import Kind, provider_schemas
from apps.providers.scoped_settings import CAPABILITIES_KEY


def _setting_field_names(catalog: dict) -> set[str]:
    omit = {"model", "language", "provider", "name", "kind"}
    return {
        name
        for name, meta in catalog.get("fields", {}).items()
        if name not in omit and not meta.get("secret")
    }


def test_every_stt_tts_provider_has_capabilities():
    missing: list[str] = []
    for kind in (Kind.STT, Kind.TTS):
        for provider, catalog in provider_schemas(kind).items():
            if CAPABILITIES_KEY not in catalog:
                missing.append(f"{kind.value}/{provider}")
    assert not missing, f"Missing capabilities: {missing}"


def test_llm_providers_do_not_have_capabilities():
    for provider, catalog in provider_schemas(Kind.LLM).items():
        assert CAPABILITIES_KEY not in catalog, provider


def test_capabilities_languages_use_canonical_keys():
    from apps.providers.languages import LANGUAGES

    errors: list[str] = []
    for kind in (Kind.STT, Kind.TTS):
        for provider, catalog in provider_schemas(kind).items():
            for model, entry in catalog[CAPABILITIES_KEY].items():
                langs = entry["languages"]
                settings = entry["settings"]
                if set(langs) != set(settings):
                    errors.append(
                        f"{kind.value}/{provider}/{model}: "
                        f"languages keys {sorted(langs)} != settings keys {sorted(settings)}"
                    )
                for canonical in langs:
                    if canonical not in LANGUAGES:
                        errors.append(
                            f"{kind.value}/{provider}/{model}: "
                            f"unknown canonical {canonical!r}"
                        )
    assert not errors, "Canonical key errors:\n" + "\n".join(errors)


def test_scoped_setting_names_match_config_fields():
    errors: list[str] = []
    for kind in (Kind.STT, Kind.TTS):
        for provider, catalog in provider_schemas(kind).items():
            caps = catalog[CAPABILITIES_KEY]
            allowed = _setting_field_names(catalog)
            for model, entry in caps.items():
                for lang, settings in entry["settings"].items():
                    unknown = set(settings) - allowed
                    if unknown:
                        errors.append(
                            f"{kind.value}/{provider} model={model} lang={lang}: "
                            f"{sorted(unknown)}"
                        )
    assert not errors, "Unknown setting names in trees:\n" + "\n".join(errors)


def test_scoped_models_align_with_model_examples():
    errors: list[str] = []
    for kind in (Kind.STT, Kind.TTS):
        for provider, catalog in provider_schemas(kind).items():
            caps = catalog[CAPABILITIES_KEY]
            examples = catalog.get("fields", {}).get("model", {}).get("examples") or []
            if not examples:
                continue
            example_set = set(examples)
            caps_set = set(caps)
            if caps_set != example_set:
                errors.append(
                    f"{kind.value}/{provider}: capabilities={sorted(caps_set)} "
                    f"examples={sorted(example_set)}"
                )
    assert not errors, "Model key mismatches:\n" + "\n".join(errors)


def test_sarvam_voice_options_split_by_model():
    catalog = provider_schemas(Kind.TTS)["sarvam"]
    caps = catalog[CAPABILITIES_KEY]
    v2 = caps["bulbul:v2"]["settings"]["hi"]["voice"]["options"]
    v3 = caps["bulbul:v3"]["settings"]["hi"]["voice"]["options"]
    assert "anushka" in v2
    assert "shubh" in v3
    assert "shubh" not in v2


def test_smallest_pro_voices_only_on_pro_model():
    catalog = provider_schemas(Kind.TTS)["smallest"]
    caps = catalog[CAPABILITIES_KEY]
    std = caps["lightning_v3.1"]["settings"]["en"]["voice"]["options"]
    pro = caps["lightning_v3.1_pro"]["settings"]["hi"]["voice"]["options"]
    assert "meher" not in std
    assert "meher" in pro


def test_deepgram_aura_voices_split():
    catalog = provider_schemas(Kind.TTS)["deepgram"]
    caps = catalog[CAPABILITIES_KEY]
    aura2 = caps["aura-2"]["settings"]["en"]["voice"]["options"]
    aura1 = caps["aura-1"]["settings"]["en"]["voice"]["options"]
    assert all(v.startswith("aura-2-") for v in aura2)
    assert all(not v.startswith("aura-2-") for v in aura1)
