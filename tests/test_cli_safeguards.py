"""Deletion plans are rechecked after confirmation, using disposable files only."""
import builtins
import hashlib

import pytest

from fileherder import DuplicateGroup
from fileherder import cli as module


@pytest.fixture
def plan(tmp_path, monkeypatch):
    keeper = tmp_path / "keep.txt"
    candidate = tmp_path / "copy.txt"
    content = b"authored duplicate bytes"
    keeper.write_bytes(content)
    candidate.write_bytes(content)
    group = DuplicateGroup(hashlib.sha256(content).hexdigest(),
                           [keeper, candidate], len(content) * 2, len(content), 2)
    cli = module.FileHerderCLI()
    monkeypatch.setattr(cli, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_display_duplicates_table", lambda groups: None)
    monkeypatch.setattr(builtins, "input", lambda prompt: "yes")
    return cli, group, keeper, candidate, content


@pytest.mark.parametrize("change", ["keeper_changed", "candidate_changed", "keeper_missing"])
def test_confirmation_cannot_authorize_stale_duplicate_bytes(plan, monkeypatch, change):
    cli, group, keeper, candidate, content = plan

    def confirm(*args, **kwargs):
        if change == "keeper_changed":
            keeper.write_bytes(b"changed keeper")
        elif change == "candidate_changed":
            candidate.write_bytes(b"unique new candidate")
        else:
            keeper.unlink()
        return True

    monkeypatch.setattr(module.Confirm, "ask", confirm)
    # The published code prompts through input(); the fixed CLI owns confirmation.
    monkeypatch.setattr(builtins, "input", lambda prompt: (confirm(), "yes")[1])
    status = cli._delete_duplicates_interactive([group])
    assert candidate.read_bytes() == (b"unique new candidate" if change == "candidate_changed" else content)
    assert status == 1


def test_valid_confirmed_duplicate_keeps_one_copy(plan, monkeypatch):
    cli, group, keeper, candidate, content = plan
    monkeypatch.setattr(module.Confirm, "ask", lambda *args, **kwargs: True)
    assert cli._delete_duplicates_interactive([group]) == 0
    assert keeper.read_bytes() == content
    assert not candidate.exists()


def test_cancellation_preserves_both_copies(plan, monkeypatch):
    cli, group, keeper, candidate, content = plan
    monkeypatch.setattr(module.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(builtins, "input", lambda prompt: "no")
    assert cli._delete_duplicates_interactive([group]) == 0
    assert keeper.read_bytes() == candidate.read_bytes() == content


def test_duplicate_command_propagates_delete_failure(plan, tmp_path, monkeypatch):
    cli, group, keeper, candidate, content = plan
    monkeypatch.setattr(cli.herder, "find_duplicates", lambda *args, **kwargs: [group])
    monkeypatch.setattr(cli, "_delete_duplicates_interactive", lambda groups: 1)
    monkeypatch.setattr(module.Confirm, "ask", lambda *args, **kwargs: True)
    assert cli.find_duplicates_command(str(tmp_path), delete=True) == 1
    assert keeper.read_bytes() == candidate.read_bytes() == content


def test_requested_delete_without_rich_is_not_silent_success(plan, tmp_path, monkeypatch):
    cli, group, keeper, candidate, content = plan
    cli.console = None
    monkeypatch.setattr(cli.herder, "find_duplicates", lambda *args, **kwargs: [group])
    assert cli.find_duplicates_command(str(tmp_path), delete=True) == 1
    assert keeper.read_bytes() == candidate.read_bytes() == content


def test_symlink_loop_after_confirmation_is_refused_without_crashing(plan, monkeypatch):
    cli, group, keeper, candidate, content = plan

    def confirm(*args, **kwargs):
        candidate.unlink()
        candidate.symlink_to(candidate.name)
        return True

    monkeypatch.setattr(module.Confirm, "ask", confirm)
    assert cli._delete_duplicates_interactive([group]) == 1
    assert keeper.read_bytes() == content
    assert candidate.is_symlink()
