"""Smoke tests for Two wallet ops (no Toga)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def test_wallet_roundtrip(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="beez-two-wallet-"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp))
    monkeypatch.setenv("HOME", str(tmp / "home"))
    (tmp / "home").mkdir(parents=True, exist_ok=True)

    import ops

    # Force app storage into temp via monkeypatch of storage dir
    st = ops.wallet_status()
    assert st.get("ok") is True
    assert st.get("has_wallet") is False

    created = ops.wallet_create()
    assert created.get("ok") is True
    assert created.get("mnemonic")
    assert created.get("address", "").startswith("bez")

    st2 = ops.wallet_status()
    assert st2.get("has_wallet") is True
    assert st2.get("address") == created["address"]

    # Mnemonic must not leak from status
    assert "mnemonic" not in st2

    forgot = ops.wallet_forget()
    assert forgot.get("ok") is True
    assert ops.wallet_status().get("has_wallet") is False

    imported = ops.wallet_import({"mnemonic": created["mnemonic"]})
    assert imported.get("ok") is True
    assert imported.get("address") == created["address"]
