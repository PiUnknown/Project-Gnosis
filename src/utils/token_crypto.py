"""Authenticated encryption for per-job GitHub credentials."""
import os


class TokenEncryptionError(RuntimeError):
    """Raised when a GitHub token cannot be safely encrypted or decrypted."""


def _fernet():
    key = (os.getenv("GNOSIS_TOKEN_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise TokenEncryptionError(
            "Per-request GitHub tokens require GNOSIS_TOKEN_ENCRYPTION_KEY."
        )
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii"))
    except ImportError as exc:
        raise TokenEncryptionError(
            "Token encryption support is unavailable; install project requirements."
        ) from exc
    except Exception as exc:
        raise TokenEncryptionError(
            "GNOSIS_TOKEN_ENCRYPTION_KEY is invalid; use a Fernet key."
        ) from exc


def encrypt_github_token(token: str) -> str:
    """Encrypt a submitted token; never persist or queue the plaintext value."""
    if not token:
        return ""
    try:
        return _fernet().encrypt(token.encode("utf-8")).decode("ascii")
    except TokenEncryptionError:
        raise
    except Exception as exc:
        raise TokenEncryptionError("Could not encrypt the GitHub token.") from exc


def decrypt_github_token(ciphertext: str) -> str:
    """Decrypt a stored token using the API/worker shared Fernet key."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except TokenEncryptionError:
        raise
    except Exception as exc:
        raise TokenEncryptionError(
            "Could not decrypt the stored GitHub token; verify the shared encryption key."
        ) from exc
