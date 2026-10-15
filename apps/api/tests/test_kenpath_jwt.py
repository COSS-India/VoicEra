"""Unit tests for the shared Kenpath JWT construction (apps.providers.adapters.kenpath.catalog.generate_jwt).

Previously duplicated inline inside KenpathLLMService._generate_jwt and
BharatVistaarLLMService._generate_jwt — these tests lock in that both
backends' payload shapes still match what those two services produced
before the extraction.
"""

from __future__ import annotations

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.providers.adapters.kenpath.catalog import generate_jwt


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def test_vistaar_payload_shape_matches_kenpath_llm_service(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    token = generate_jwt(private_pem, backend="vistaar", subject="+91-9036722772")

    decoded = pyjwt.decode(token, public_pem, algorithms=["RS256"])
    assert decoded["sub"] == "+91-9036722772"
    assert decoded["iss"] == "voice-provider"
    assert "iat" in decoded and "exp" in decoded
    assert decoded["exp"] - decoded["iat"] == 3600
    # Bharat Vistaar-only fields must not leak into the vistaar payload.
    assert "user_id" not in decoded
    assert "tenant_id" not in decoded


def test_bharatvistaar_payload_shape_matches_bharat_vistaar_llm_service(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    token = generate_jwt(private_pem, backend="bharatvistaar", subject="session-abc-123")

    decoded = pyjwt.decode(token, public_pem, algorithms=["RS256"])
    assert decoded["user_id"] == "session-abc-123"
    assert decoded["tenant_id"] == "session-abc-123"
    assert decoded["iss"] == "samvaad"
    assert "iat" in decoded and "exp" in decoded
    assert decoded["exp"] - decoded["iat"] == 3600
    # Vistaar-only field must not leak into the bharatvistaar payload.
    assert "sub" not in decoded
