import os
import re

import pytest

from common import DecryptionError, KEY_BYTES, MAX_PLAINTEXT, MIN_BODY, NONCE_BYTES, TAG_BYTES
import crypto
from crypto import decrypt, encrypt, key_fingerprint, load_key, synced_folder


@pytest.fixture
def key():
    return os.urandom(KEY_BYTES)


@pytest.mark.parametrize("msg", ["hello", "", "café", "emoji 🔐", "x" * MAX_PLAINTEXT])
def test_round_trip(key, msg):
    assert decrypt(encrypt(msg, key), key) == msg


def test_blob_layout(key):
    blob = encrypt("hello", key)
    assert len(blob) == NONCE_BYTES + len(b"hello") + TAG_BYTES


def test_same_message_gives_different_output(key):
    a, b = encrypt("hello", key), encrypt("hello", key)
    assert a != b
    assert a[:NONCE_BYTES] != b[:NONCE_BYTES]


def test_wrong_key_fails(key):
    blob = encrypt("hello", key)
    with pytest.raises(DecryptionError):
        decrypt(blob, os.urandom(KEY_BYTES))


def test_any_bit_flip_fails(key):
    blob = encrypt("hello", key)
    for i in range(len(blob) * 8):
        tampered = bytearray(blob)
        tampered[i // 8] ^= 1 << (i % 8)
        with pytest.raises(DecryptionError):
            decrypt(bytes(tampered), key)


def test_truncated_blob_fails(key):
    blob = encrypt("hello", key)
    for n in (0, NONCE_BYTES, len(blob) - 1):
        with pytest.raises(DecryptionError):
            decrypt(blob[:n], key)


def test_oversized_message_rejected(key):
    with pytest.raises(ValueError):
        encrypt("x" * (MAX_PLAINTEXT + 1), key)


def test_oversized_counts_utf8_bytes_not_chars(key):
    # "é" is 2 bytes in UTF-8, so this is under the char limit but over the byte limit
    with pytest.raises(ValueError):
        encrypt("é" * (MAX_PLAINTEXT // 2 + 1), key)


def test_load_key_from_path(tmp_path):
    p = tmp_path / "key.bin"
    k = os.urandom(KEY_BYTES)
    p.write_bytes(k)
    assert load_key(str(p)) == k


def test_load_key_from_env(tmp_path, monkeypatch):
    p = tmp_path / "key.bin"
    k = os.urandom(KEY_BYTES)
    p.write_bytes(k)
    monkeypatch.setenv("FV_KEY_PATH", str(p))
    assert load_key() == k


@pytest.mark.parametrize("size", [0, 16, 31, 33, 64])
def test_load_key_wrong_size(tmp_path, size):
    p = tmp_path / "key.bin"
    p.write_bytes(os.urandom(size))
    with pytest.raises(ValueError):
        load_key(str(p))


def test_load_key_missing(monkeypatch):
    monkeypatch.delenv("FV_KEY_PATH", raising=False)
    with pytest.raises((ValueError, FileNotFoundError)):
        load_key()


@pytest.mark.parametrize("text", ["{h}", "{h}\n", "{H}\n", "  {h}  \r\n"])
def test_load_key_hex(tmp_path, text):
    k = os.urandom(KEY_BYTES)
    p = tmp_path / "key.hex"
    p.write_text(text.format(h=k.hex(), H=k.hex().upper()))
    assert load_key(str(p)) == k


def test_load_key_hex_wrong_length(tmp_path):
    p = tmp_path / "key.hex"
    p.write_text(os.urandom(16).hex() + "\n")
    with pytest.raises(ValueError):
        load_key(str(p))


def test_load_key_huge_file(tmp_path):
    p = tmp_path / "big"
    p.write_bytes(b"0" * 10_000)
    with pytest.raises(ValueError, match="too large"):
        load_key(str(p))


def test_load_key_error_does_not_leak_contents(tmp_path):
    p = tmp_path / "key.hex"
    secret = "ab" * 31 + "zz"  # 64 chars, not valid hex
    p.write_text(secret)
    with pytest.raises(ValueError) as e:
        load_key(str(p))
    assert secret not in str(e.value)


def test_load_key_warns_on_loose_permissions(tmp_path, capsys):
    p = tmp_path / "key.bin"
    p.write_bytes(os.urandom(KEY_BYTES))
    p.chmod(0o644)
    load_key(str(p))
    assert "chmod 600" in capsys.readouterr().err
    p.chmod(0o600)
    load_key(str(p))
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("size", [16, 24])
def test_short_aes_keys_rejected(size):
    # AESGCM itself would accept these and silently run AES-128/192
    with pytest.raises(ValueError):
        encrypt("hello", os.urandom(size))
    with pytest.raises(ValueError):
        decrypt(b"x" * MIN_BODY, os.urandom(size))


def test_fingerprint():
    k = os.urandom(KEY_BYTES)
    fp = key_fingerprint(k)
    assert re.fullmatch(r"[0-9a-f]{4}-[0-9a-f]{4}", fp)
    assert key_fingerprint(k) == fp
    assert key_fingerprint(os.urandom(KEY_BYTES)) != fp
    assert k.hex()[:8] not in fp.replace("-", "")


def test_oversized_blob_fails(key):
    with pytest.raises(DecryptionError):
        decrypt(os.urandom(513), key)


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    for d in ("Desktop", "Documents", "Library/CloudStorage/Dropbox"):
        (home / d).mkdir(parents=True)
    return home


@pytest.mark.parametrize("folder", ["Desktop", "Documents"])
def test_synced_folder_icloud_desktop_documents(fake_home, folder):
    (fake_home / "Library/Mobile Documents/com~apple~CloudDocs" / folder).mkdir(parents=True)
    assert synced_folder(str(fake_home / folder / "key.bin"), str(fake_home)) == "iCloud Desktop & Documents"


def test_synced_folder_desktop_without_icloud(fake_home):
    assert synced_folder(str(fake_home / "Desktop/key.bin"), str(fake_home)) is None


def test_synced_folder_icloud_drive(fake_home):
    p = fake_home / "Library/Mobile Documents/com~apple~CloudDocs/key.bin"
    assert synced_folder(str(p), str(fake_home)) == "iCloud Drive"


def test_synced_folder_cloud_storage(fake_home):
    p = fake_home / "Library/CloudStorage/Dropbox/key.bin"
    assert synced_folder(str(p), str(fake_home)) == "cloud storage"


def test_synced_folder_outside_home(fake_home, tmp_path):
    assert synced_folder(str(tmp_path / "key.bin"), str(fake_home)) is None
    # A sibling whose name only starts with "Desktop" is not inside it
    (fake_home / "Library/Mobile Documents/com~apple~CloudDocs/Desktop").mkdir(parents=True)
    assert synced_folder(str(fake_home / "Desktop2/key.bin"), str(fake_home)) is None


def test_load_key_warns_when_synced(tmp_path, monkeypatch, capsys):
    p = tmp_path / "key.bin"
    p.write_bytes(os.urandom(KEY_BYTES))
    p.chmod(0o600)
    monkeypatch.setattr(crypto, "synced_folder", lambda path: "iCloud Drive")
    load_key(str(p))
    assert "may sync to iCloud Drive" in capsys.readouterr().err
