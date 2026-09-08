"""Azure Speech Services model catalog."""

from ...capabilities import expand_settings

# Azure Neural TTS voices (curated; full catalogue has hundreds)
TTS_VOICES: tuple[str, ...] = (
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-US-DavisNeural",
    "en-US-AmberNeural",
    "en-US-AnaNeural",
    "en-US-AshleyNeural",
    "en-US-BrandonNeural",
    "en-US-ChristopherNeural",
    "en-US-ElizabethNeural",
    "en-US-EricNeural",
    "en-US-JacobNeural",
    "en-US-MichelleNeural",
    "en-US-MonicaNeural",
    "en-US-NancyNeural",
    "en-US-RogerNeural",
    "en-US-SaraNeural",
    "en-US-SteffanNeural",
    "en-US-TonyNeural",
)
DEFAULT_TTS_VOICE = "en-US-AriaNeural"

# Azure Speech service regions
SPEECH_REGIONS: tuple[str, ...] = (
    "eastus", "eastus2", "westus", "westus2", "westus3",
    "centralus", "northcentralus", "southcentralus", "westcentralus",
    "westeurope", "northeurope",
    "uksouth", "ukwest",
    "francecentral", "switzerlandnorth", "germanywestcentral", "norwayeast",
    "australiaeast",
    "eastasia", "southeastasia",
    "japaneast", "japanwest",
    "koreacentral",
    "centralindia", "southindia",
    "brazilsouth",
)

_AZURE_LANGS = {
    "en-US": "en-US",
    "en-GB": "en-GB",
    "en-AU": "en-AU",
    "en-CA": "en-CA",
    "en-IN": "en",
    "hi-IN": "hi",
}

_SPEED = {
    "default": 1.0,
    "minimum": 0.5,
    "maximum": 2.0,
    "input_type": "slider",
}

# Pipecat Azure STT does not take these model names (uses default recognizer).
# Kept as catalog labels only — settings tree is empty.
STT_CAPABILITIES: dict[str, dict] = {
    model: {
        "languages": dict(_AZURE_LANGS),
        "settings": expand_settings(_AZURE_LANGS, {}),
    }
    for model in ("latest_long", "latest_short")
}

# Voice locale should match language. Curated list is en-US only;
# other languages allow custom Neural voice names.
# Settings keys are vendor codes (hi-IN, not canonical hi).
TTS_CAPABILITIES: dict[str, dict] = {
    "neural": {
        "languages": dict(_AZURE_LANGS),
        "settings": {
            "en-US": {
                "voice": {
                    "default": DEFAULT_TTS_VOICE,
                    "options": list(TTS_VOICES),
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_SPEED),
            },
            "en-GB": {
                "voice": {
                    "default": "en-GB-SoniaNeural",
                    "options": [],
                    "input_type": "both",
                    "allow_custom_input": True,
                    "description": "Enter an Azure Neural voice for en-GB (e.g. en-GB-SoniaNeural).",
                },
                "speed": dict(_SPEED),
            },
            "en-AU": {
                "voice": {
                    "default": "en-AU-NatashaNeural",
                    "options": [],
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_SPEED),
            },
            "en-CA": {
                "voice": {
                    "default": "en-CA-ClaraNeural",
                    "options": [],
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_SPEED),
            },
            "en-IN": {
                "voice": {
                    "default": "en-IN-NeerjaNeural",
                    "options": [],
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_SPEED),
            },
            "hi-IN": {
                "voice": {
                    "default": "hi-IN-SwaraNeural",
                    "options": [],
                    "input_type": "both",
                    "allow_custom_input": True,
                },
                "speed": dict(_SPEED),
            },
        },
    },
}
