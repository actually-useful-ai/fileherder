"""Synthetic file-operation regressions; all sentinels live under tmp_path."""

from pathlib import Path

import pytest

from fileherder.core import DuplicateFinder, FileOrganizer
from fileherder.operations import (
    copy_files,
    delete_files_safe,
    move_files,
    rename_files_batch,
    validate_paths,
)


@pytest.mark.parametrize("operation", [copy_files, move_files])
def test_dangling_destination_link_is_an_occupied_name(tmp_path, operation):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    source.mkdir(); destination.mkdir(); outside.mkdir()
    original = source / "item.txt"
    original.write_text("new content")
    external_target = outside / "absent.txt"
    conflict = destination / original.name
    conflict.symlink_to(external_target)

    result = operation([original], destination, overwrite=False)

    assert result.success
    assert conflict.is_symlink()
    assert not external_target.exists()
    assert (destination / "item_1.txt").read_text() == "new content"


@pytest.mark.parametrize("operation", [copy_files, move_files])
@pytest.mark.parametrize("target_kind", ["link", "dangling_link", "directory"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_overwrite_refuses_nonregular_destination_entries(
    tmp_path, operation, target_kind, dry_run
):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    source.mkdir(); destination.mkdir(); outside.mkdir()
    original = source / "item.txt"
    original.write_text("new content")
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep content")
    conflict = destination / original.name
    if target_kind == "directory":
        conflict.mkdir()
    else:
        conflict.symlink_to(sentinel if target_kind == "link" else outside / "absent.txt")

    result = operation([original], destination, overwrite=True, dry_run=dry_run)

    assert not result.success
    assert result.failure_count == 1
    assert original.read_text() == "new content"
    assert sentinel.read_text() == "keep content"
    assert not (outside / "absent.txt").exists()
    assert conflict.is_dir() if target_kind == "directory" else conflict.is_symlink()


@pytest.mark.parametrize("new_name", ["../outside/escaped.txt", "nested/name.txt", r"nested\name.txt", "", ".", ".."])
def test_rename_accepts_only_a_leaf_name(tmp_path, new_name):
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir(); outside.mkdir()
    original = source / "item.txt"
    original.write_text("keep content")
    (source / "nested").mkdir()

    result = rename_files_batch({original: new_name})

    assert not result.success
    assert original.read_text() == "keep content"
    assert not (outside / "escaped.txt").exists()


def test_rename_refuses_an_absolute_destination(tmp_path):
    original = tmp_path / "item.txt"
    original.write_text("keep content")
    target = tmp_path / "outside.txt"
    result = rename_files_batch({original: str(target)})
    assert not result.success
    assert original.read_text() == "keep content"
    assert not target.exists()


def test_rename_preserves_a_dangling_destination_link(tmp_path):
    original = tmp_path / "item.txt"
    original.write_text("keep content")
    conflict = tmp_path / "renamed.txt"
    conflict.symlink_to(tmp_path / "absent.txt")
    result = rename_files_batch({original: conflict.name})
    assert not result.success
    assert original.read_text() == "keep content"
    assert conflict.is_symlink()


@pytest.mark.parametrize("operation", [copy_files, move_files, delete_files_safe, rename_files_batch])
@pytest.mark.parametrize("source_kind", ["directory", "link", "dangling_link"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_mutations_refuse_nonregular_sources(tmp_path, operation, source_kind, dry_run):
    original = tmp_path / "source"
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep content")
    if source_kind == "directory":
        original.mkdir()
        (original / "nested.txt").write_text("nested content")
    else:
        original.symlink_to(sentinel if source_kind == "link" else tmp_path / "absent.txt")

    if operation is delete_files_safe:
        result = operation([original], require_confirmation=False, dry_run=dry_run)
    elif operation is rename_files_batch:
        result = operation({original: "renamed"}, dry_run=dry_run)
    else:
        result = operation([original], tmp_path / "destination", dry_run=dry_run)

    assert not result.success
    assert result.failure_count == 1
    assert sentinel.read_text() == "keep content"
    assert original.is_dir() if source_kind == "directory" else original.is_symlink()


def test_move_to_own_directory_does_not_suffix_rename(tmp_path):
    original = tmp_path / "item.txt"
    original.write_text("keep content")
    move_files([original], tmp_path)
    assert original.read_text() == "keep content"
    assert not (tmp_path / "item_1.txt").exists()


def test_copy_to_own_directory_keeps_existing_suffix_behavior(tmp_path):
    original = tmp_path / "item.txt"
    original.write_text("keep content")
    result = copy_files([original], tmp_path)
    assert result.success
    assert original.read_text() == "keep content"
    assert (tmp_path / "item_1.txt").read_text() == "keep content"


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("target_kind", ["link", "dangling_link", "file"])
def test_organizer_refuses_unsafe_category_destinations(tmp_path, dry_run, target_kind):
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir(); outside.mkdir()
    original = source / "item.py"
    original.write_text("keep content")
    category = source / "code"
    if target_kind == "file":
        category.write_text("keep category entry")
    else:
        category.symlink_to(outside if target_kind == "link" else tmp_path / "absent")

    result = FileOrganizer().organize_directory(source, dry_run=dry_run)

    assert not result.success
    assert result.error
    assert result.files_organized == 0
    assert original.read_text() == "keep content"
    assert not (outside / "item.py").exists()


def test_organizer_reports_partial_move_failure(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked.py"
    allowed = tmp_path / "allowed.txt"
    blocked.write_text("blocked content")
    allowed.write_text("allowed content")
    original_rename = Path.rename

    def rename(path, destination):
        if path == blocked:
            raise PermissionError("synthetic move denial")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", rename)
    result = FileOrganizer().organize_directory(tmp_path)
    assert not result.success
    assert result.files_organized == 1
    assert "synthetic move denial" in result.error
    assert blocked.read_text() == "blocked content"
    assert (tmp_path / "text/allowed.txt").read_text() == "allowed content"


def test_organizer_ignores_source_symlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep content")
    link = source / "alias.txt"
    link.symlink_to(sentinel)
    result = FileOrganizer().organize_directory(source)
    assert result.success
    assert result.files_organized == 0
    assert link.is_symlink()
    assert sentinel.read_text() == "keep content"


@pytest.mark.parametrize("chunk_size", [0, -1, True, False, 1.5, "8192", None])
def test_duplicate_finder_requires_positive_integer_chunks(chunk_size):
    with pytest.raises(ValueError, match="chunk_size"):
        DuplicateFinder(chunk_size=chunk_size)


def test_duplicate_groups_exclude_symlink_representatives(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("independent copies")
    second.write_text("independent copies")
    alias = tmp_path / "alias.txt"
    alias.symlink_to(first)
    groups = DuplicateFinder().find_duplicates(tmp_path)
    assert len(groups) == 1
    assert set(groups[0].files) == {first, second}
    assert groups[0].count == 2


def test_delete_cancel_preserves_regular_source(tmp_path, monkeypatch):
    original = tmp_path / "item.txt"
    original.write_text("keep content")
    monkeypatch.setattr("builtins.input", lambda _: "no")
    result = delete_files_safe([original])
    assert not result.success
    assert result.success_count == 0
    assert original.read_text() == "keep content"


@pytest.mark.parametrize("dangling", [False, True])
def test_public_path_validation_agrees_with_mutation_link_refusal(tmp_path, dangling):
    target = tmp_path / "target.txt"
    if not dangling:
        target.write_text("keep content")
    link = tmp_path / "alias.txt"
    link.symlink_to(target)
    valid, errors = validate_paths([link])
    assert not valid
    assert len(errors) == 1
    assert errors[0][0] == link
    assert link.is_symlink()
