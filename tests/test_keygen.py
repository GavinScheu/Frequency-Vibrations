import os
import stat
import sys

import pytest

import keygen
from crypto import key_fingerprint, load_key


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["keygen.py", *args])
    return keygen.main()


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_default_binary_key(monkeypatch, capsys):
    assert run(monkeypatch) == 0
    assert os.path.getsize("key.bin") == 32
    assert stat.S_IMODE(os.stat("key.bin").st_mode) == 0o600
    key = load_key("key.bin")
    out = capsys.readouterr().out
    assert key_fingerprint(key) in out
    assert key.hex() not in out


def test_hex_key(monkeypatch, capsys):
    assert run(monkeypatch, "--hex") == 0
    assert stat.S_IMODE(os.stat("key.hex").st_mode) == 0o600
    key = load_key("key.hex")
    assert open("key.hex").read() == key.hex() + "\n"
    assert key.hex() not in capsys.readouterr().out


def test_refuses_overwrite(monkeypatch, capsys):
    run(monkeypatch)
    before = open("key.bin", "rb").read()
    assert run(monkeypatch) == 1
    assert "already exists" in capsys.readouterr().err
    assert open("key.bin", "rb").read() == before


def test_force_replaces(monkeypatch):
    run(monkeypatch)
    before = open("key.bin", "rb").read()
    assert run(monkeypatch, "--force") == 0
    assert open("key.bin", "rb").read() != before
    assert stat.S_IMODE(os.stat("key.bin").st_mode) == 0o600
    assert not os.path.exists("key.bin.tmp")


def test_custom_out(monkeypatch):
    assert run(monkeypatch, "--out", "shared.key") == 0
    assert len(load_key("shared.key")) == 32
