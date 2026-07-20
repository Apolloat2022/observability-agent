"""Phase 5 — verify_ledger.py CLI offline tests (arg parsing, URL
resolution). Live chain-verification behavior is proven against real Neon
in tests/integration/test_neon_ledger.py."""
from __future__ import annotations

import pytest

from obsvagent.cli.verify_ledger import _resolve_database_url


def test_explicit_url_wins():
    assert _resolve_database_url("postgresql://explicit/db") == "postgresql://explicit/db"


def test_no_url_anywhere_exits_with_code_2(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OBSV_APP_DATABASE_URL", raising=False)
    monkeypatch.setattr("obsvagent.cli.verify_ledger.get_app_database_url", lambda: None)
    monkeypatch.setattr("obsvagent.cli.verify_ledger.get_database_url", lambda: None)
    with pytest.raises(SystemExit) as exc_info:
        _resolve_database_url(None)
    assert exc_info.value.code == 2
