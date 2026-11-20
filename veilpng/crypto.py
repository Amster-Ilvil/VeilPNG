"""Authenticated payload encryption. Uses Argon2id and AES-256-GCM."""
from __future__ import annotations

import os
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class KDFParams:
    memory_kib: int = 65536
    time_cost: int = 3
    parallelism: int = 1

    def validate(self) -> None:
        # Prevent an attacker-supplied header from requesting excessive resources.
        if not (8192 <= self.memory_kib <= 262144):
            raise ValueError("Argon2id memory parameter is out of supported range")
        if not (1 <= self.time_cost <= 8):
            raise ValueError("Argon2id time parameter is out of supported range")
        if not (1 <= self.parallelism <= 4):
            raise ValueError("Argon2id parallelism parameter is out of supported range")


def derive_key(password: str, salt: bytes, params: KDFParams) -> bytes:
    if not password:
        raise ValueError("Password cannot be empty")
    if len(salt) != 16:
        raise ValueError("Invalid Argon2id salt length")
    params.validate()
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_kib,
        parallelism=params.parallelism,
        hash_len=32,
        type=Type.ID,
    )


def encrypt_payload(plaintext: bytes, password: str, aad: bytes, params: KDFParams) -> tuple[bytes, bytes, bytes]:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    ciphertext = AESGCM(derive_key(password, salt, params)).encrypt(nonce, plaintext, aad)
    return salt, nonce, ciphertext


def decrypt_payload(ciphertext: bytes, password: str, salt: bytes, nonce: bytes, aad: bytes, params: KDFParams) -> bytes:
    if len(nonce) != 12:
        raise ValueError("Invalid AES-GCM nonce length")
    return AESGCM(derive_key(password, salt, params)).decrypt(nonce, ciphertext, aad)
