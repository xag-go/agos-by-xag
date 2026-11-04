from pathlib import Path

import pytest

from agos_core.security.secrets import decrypt_secret, encrypt_secret, load_or_create_master_key

# Produced by the earlier TypeScript implementation: existing data must keep working.
TS_SEALED = "v1.8y4stYcUfjtpKWIg.Rjr6uUk1cySxXATVTBWDsg.QAgBvxK1erDNBZM"


def test_compatible_with_typescript_data() -> None:
    assert decrypt_secret(bytes([7] * 32), TS_SEALED, "provider:claude:api") == "sk-test-123"


def test_secrets(tmp_path: Path) -> None:
    key = bytes([7] * 32)
    sealed = encrypt_secret(key, "sk-test-123", "provider:claude:api")
    assert "sk-test" not in sealed
    assert decrypt_secret(key, sealed, "provider:claude:api") == "sk-test-123"
    with pytest.raises(Exception):  # noqa: B017 - any failure is correct here
        decrypt_secret(key, sealed, "provider:openai:api")
    with pytest.raises(Exception):  # noqa: B017
        decrypt_secret(bytes([8] * 32), sealed, "provider:claude:api")
    file = tmp_path / "system" / "master.key"
    first = load_or_create_master_key(file)
    assert file.stat().st_mode & 0o777 == 0o600
    assert load_or_create_master_key(file) == first
    file.write_text("short")
    with pytest.raises(ValueError, match="damaged"):
        load_or_create_master_key(file)
