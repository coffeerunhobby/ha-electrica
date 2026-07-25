"""Tests for at-rest encryption of the stored password.

Requires Home Assistant (crypto.py imports its Store helper); skipped otherwise.
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.electrica.crypto import (  # noqa: E402
    PREFIX,
    ElectricaCipher,
    is_encrypted,
)

SECRET = "synthetic-password-not-real"


@pytest.fixture
def cipher() -> ElectricaCipher:
    return ElectricaCipher(ElectricaCipher._generate_key().encode())


def test_round_trip(cipher: ElectricaCipher):
    token = cipher.encrypt(SECRET)
    assert cipher.decrypt(token) == SECRET


def test_ciphertext_does_not_contain_the_secret(cipher: ElectricaCipher):
    token = cipher.encrypt(SECRET)
    assert SECRET not in token
    assert is_encrypted(token)


def test_encryption_is_non_deterministic(cipher: ElectricaCipher):
    # A random IV means an observer cannot tell that two entries share a
    # password, nor confirm a guess by comparing ciphertexts.
    assert cipher.encrypt(SECRET) != cipher.encrypt(SECRET)


def test_plaintext_passes_through_for_migration(cipher: ElectricaCipher):
    # Values written before encryption existed are untagged and must survive
    # unchanged so __init__ can migrate them in place.
    assert is_encrypted(SECRET) is False
    assert cipher.decrypt(SECRET) == SECRET


def test_a_different_key_cannot_decrypt(cipher: ElectricaCipher):
    other = ElectricaCipher(ElectricaCipher._generate_key().encode())
    with pytest.raises(ValueError):
        other.decrypt(cipher.encrypt(SECRET))


def test_tampering_is_detected(cipher: ElectricaCipher):
    token = cipher.encrypt(SECRET)
    tampered = PREFIX + token[len(PREFIX) : -4] + "AAAA"
    with pytest.raises(ValueError):
        cipher.decrypt(tampered)


@pytest.mark.parametrize("value", [None, "", "plain", "encv1:x"])
def test_is_encrypted_rejects_untagged_values(value):
    assert is_encrypted(value) is False
