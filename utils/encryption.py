"""
utils/encryption.py — Fernet-based credential encryption.

Encrypts broker API keys and passwords before storing in SQLite.
Each account's credentials are encrypted as a JSON blob using a
master key from the .env file.
"""

import json
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_fernet(master_key: str) -> Fernet:
    """Create a Fernet instance from the master key string."""
    if not master_key:
        raise ValueError(
            "MASTER_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(master_key.encode() if isinstance(master_key, str) else master_key)


def encrypt_credentials(credentials: dict, master_key: str) -> str:
    """
    Encrypt a credentials dict into a Fernet token string.

    Parameters
    ----------
    credentials : dict
        e.g. {"login": 12345, "password": "xxx", "server": "Finex-Demo"}
    master_key : str
        The Fernet key from .env MASTER_KEY.

    Returns
    -------
    str
        Base64-encoded encrypted token.
    """
    f = _get_fernet(master_key)
    plaintext = json.dumps(credentials).encode("utf-8")
    return f.encrypt(plaintext).decode("utf-8")


def decrypt_credentials(token: str, master_key: str) -> dict:
    """
    Decrypt a Fernet token string back into a credentials dict.

    Parameters
    ----------
    token : str
        The encrypted token from the database.
    master_key : str
        The Fernet key from .env MASTER_KEY.

    Returns
    -------
    dict
        The original credentials dict.

    Raises
    ------
    InvalidToken
        If the master key is wrong or the token is corrupted.
    """
    f = _get_fernet(master_key)
    try:
        plaintext = f.decrypt(token.encode("utf-8"))
        return json.loads(plaintext.decode("utf-8"))
    except InvalidToken:
        logger.error("Failed to decrypt credentials — wrong MASTER_KEY or corrupted token")
        raise


def generate_master_key() -> str:
    """Generate a new Fernet master key. Convenience function."""
    return Fernet.generate_key().decode("utf-8")
