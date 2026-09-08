"""Runtime knowledge config parsing tests."""

from __future__ import annotations

from apps.runtime.services.knowledge.config import parse_knowledge_config
from apps.runtime.services.knowledge.formatting import augment_user_message


def test_parse_knowledge_config_disabled():
    assert parse_knowledge_config({"config": {"knowledge_base": {"enabled": False}}}) is None


def test_parse_knowledge_config_requires_document_ids():
    assert parse_knowledge_config(
        {"config": {"knowledge_base": {"enabled": True, "document_ids": []}}}
    ) is None


def test_parse_knowledge_config_tool_mode():
    cfg = parse_knowledge_config(
        {
            "config": {
                "knowledge_base": {
                    "enabled": True,
                    "mode": "tool",
                    "document_ids": ["doc-1"],
                    "top_k": 3,
                }
            }
        }
    )
    assert cfg is not None
    assert cfg.mode == "tool"
    assert cfg.document_ids == ["doc-1"]
    assert cfg.top_k == 3


def test_augment_user_message_includes_excerpts():
    augmented = augment_user_message(
        "What is the refund policy?",
        [
            {
                "text": "Refunds within 30 days.",
                "source_filename": "policy.pdf",
            }
        ],
    )
    assert "User question:" in augmented
    assert "policy.pdf" in augmented
    assert "Refunds within 30 days." in augmented
