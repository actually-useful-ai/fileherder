"""
Batch file operations for fileherder.

Provides safe, validated operations for moving, copying, deleting,
and renaming multiple files at once.

Author: Luke Steuber
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Callable

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class OperationResult:
    """
    Result from a batch file operation.

    Attributes:
        success_count: Number of successful operations
        failure_count: Number of failed operations
        total_count: Total files processed
        errors: List of (file_path, error_message) tuples
        success: Whether all operations succeeded
    """
    success_count: int
    failure_count: int
    total_count: int
    errors: List[tuple[Path, str]]
    success: bool


# ============================================================================
# Batch Operations
# ============================================================================

def _entry_exists(path: Path) -> bool:
    """A dangling symbolic link still occupies a directory entry."""
    return path.exists() or path.is_symlink()


def _require_regular_file(path: Path) -> None:
    """Refuse directories and link sources rather than following their targets."""
    if path.is_symlink():
        raise ValueError(f"Symbolic link sources are not supported: {path}")
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Source is not a regular file: {path}")


def _prepare_destination_directory(destination: Path, dry_run: bool) -> None:
    if destination.is_symlink():
        raise ValueError(f"Symbolic link destinations are not supported: {destination}")
    if destination.exists():
        if not destination.is_dir():
            raise NotADirectoryError(f"Destination is not a directory: {destination}")
    elif not dry_run:
        destination.mkdir(parents=True, exist_ok=True)


def _destination_path(
    source: Path, destination: Path, overwrite: bool, *, reject_same_file: bool = False
) -> Path:
    """Select an ordinary conflict suffix; this is not a concurrent reservation."""
    target = destination / source.name
    if _entry_exists(target):
        if ((overwrite or reject_same_file) and not target.is_symlink()
                and target.is_file() and source.samefile(target)):
            raise ValueError(f"Source and destination refer to the same file: {source}")
        if overwrite:
            if target.is_symlink() or not target.is_file():
                raise ValueError(f"Overwrite target is not a regular file: {target}")
        else:
            counter = 1
            while _entry_exists(target):
                target = destination / f"{source.stem}_{counter}{source.suffix}"
                counter += 1
    return target


def move_files(
    files: List[Path],
    destination: Path,
    overwrite: bool = False,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[int, int, Path], None]] = None
) -> OperationResult:
    """
    Move multiple files to a destination directory.

    Args:
        files: List of file paths to move
        destination: Destination directory
        overwrite: Whether to overwrite existing files
        dry_run: If True, simulate without actually moving
        progress_callback: Optional callback(current, total, file_path)

    Returns:
        OperationResult with statistics

    Example:
        >>> files = list(Path("/temp").glob("*.txt"))
        >>> result = move_files(files, Path("/archive"))
        >>> print(f"Moved {result.success_count} files")
    """
    success_count = 0
    failure_count = 0
    errors = []

    for i, file_path in enumerate(files, 1):
        if progress_callback:
            progress_callback(i, len(files), file_path)

        try:
            _require_regular_file(file_path)
            _prepare_destination_directory(destination, dry_run)
            dest_path = _destination_path(file_path, destination, overwrite, reject_same_file=True)

            if not dry_run:
                shutil.move(str(file_path), str(dest_path))

            success_count += 1
            logger.debug(f"Moved {file_path.name} -> {dest_path}")

        except Exception as e:
            failure_count += 1
            errors.append((file_path, str(e)))
            logger.error(f"Error moving {file_path}: {e}")

    return OperationResult(
        success_count=success_count,
        failure_count=failure_count,
        total_count=len(files),
        errors=errors,
        success=(failure_count == 0)
    )


def copy_files(
    files: List[Path],
    destination: Path,
    overwrite: bool = False,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[int, int, Path], None]] = None
) -> OperationResult:
    """
    Copy multiple files to a destination directory.

    Args:
        files: List of file paths to copy
        destination: Destination directory
        overwrite: Whether to overwrite existing files
        dry_run: If True, simulate without actually copying
        progress_callback: Optional callback(current, total, file_path)

    Returns:
        OperationResult with statistics

    Example:
        >>> files = list(Path("/source").glob("*.jpg"))
        >>> result = copy_files(files, Path("/backup"))
        >>> print(f"Copied {result.success_count} files")
    """
    success_count = 0
    failure_count = 0
    errors = []

    for i, file_path in enumerate(files, 1):
        if progress_callback:
            progress_callback(i, len(files), file_path)

        try:
            _require_regular_file(file_path)
            _prepare_destination_directory(destination, dry_run)
            dest_path = _destination_path(file_path, destination, overwrite)

            if not dry_run:
                shutil.copy2(str(file_path), str(dest_path))

            success_count += 1
            logger.debug(f"Copied {file_path.name} -> {dest_path}")

        except Exception as e:
            failure_count += 1
            errors.append((file_path, str(e)))
            logger.error(f"Error copying {file_path}: {e}")

    return OperationResult(
        success_count=success_count,
        failure_count=failure_count,
        total_count=len(files),
        errors=errors,
        success=(failure_count == 0)
    )


def delete_files_safe(
    files: List[Path],
    require_confirmation: bool = True,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[int, int, Path], None]] = None
) -> OperationResult:
    """
    Safely delete multiple files.

    Args:
        files: List of file paths to delete
        require_confirmation: If True, require user confirmation
        dry_run: If True, simulate without actually deleting
        progress_callback: Optional callback(current, total, file_path)

    Returns:
        OperationResult with statistics

    Example:
        >>> duplicates = [Path("/tmp/copy1.txt"), Path("/tmp/copy2.txt")]
        >>> # Dry run first to see what would be deleted
        >>> result = delete_files_safe(duplicates, dry_run=True)
        >>> print(f"Would delete {result.success_count} files")
        >>>
        >>> # Actually delete (requires confirmation)
        >>> result = delete_files_safe(duplicates, require_confirmation=True)
    """
    if require_confirmation and not dry_run:
        print(f"\nAbout to delete {len(files)} files:")
        for f in files[:5]:
            print(f"  - {f}")
        if len(files) > 5:
            print(f"  ... and {len(files) - 5} more")

        response = input("\nProceed with deletion? (yes/no): ").strip().lower()
        if response not in {'yes', 'y'}:
            logger.info("Deletion cancelled by user")
            return OperationResult(
                success_count=0,
                failure_count=0,
                total_count=len(files),
                errors=[],
                success=False
            )

    success_count = 0
    failure_count = 0
    errors = []

    for i, file_path in enumerate(files, 1):
        if progress_callback:
            progress_callback(i, len(files), file_path)

        try:
            _require_regular_file(file_path)

            if not dry_run:
                file_path.unlink()

            success_count += 1
            logger.debug(f"Deleted {file_path}")

        except Exception as e:
            failure_count += 1
            errors.append((file_path, str(e)))
            logger.error(f"Error deleting {file_path}: {e}")

    return OperationResult(
        success_count=success_count,
        failure_count=failure_count,
        total_count=len(files),
        errors=errors,
        success=(failure_count == 0)
    )


def rename_files_batch(
    rename_map: Dict[Path, str],
    dry_run: bool = False,
    progress_callback: Optional[Callable[[int, int, Path], None]] = None
) -> OperationResult:
    """
    Rename multiple files at once.

    Args:
        rename_map: Dictionary mapping file paths to new names
        dry_run: If True, simulate without actually renaming
        progress_callback: Optional callback(current, total, file_path)

    Returns:
        OperationResult with statistics

    Example:
        >>> rename_map = {
        ...     Path("/data/IMG001.jpg"): "vacation_photo_1.jpg",
        ...     Path("/data/IMG002.jpg"): "vacation_photo_2.jpg",
        ... }
        >>> result = rename_files_batch(rename_map)
        >>> print(f"Renamed {result.success_count} files")
    """
    success_count = 0
    failure_count = 0
    errors = []

    total = len(rename_map)

    for i, (old_path, new_name) in enumerate(rename_map.items(), 1):
        if progress_callback:
            progress_callback(i, total, old_path)

        try:
            _require_regular_file(old_path)
            if (not isinstance(new_name, str) or not new_name
                    or new_name in {'.', '..'} or '/' in new_name or '\\' in new_name
                    or Path(new_name).name != new_name):
                raise ValueError("New name must be a single filename, without a path")

            new_path = old_path.parent / new_name

            # Check for conflicts
            if _entry_exists(new_path) and new_path != old_path:
                raise FileExistsError(f"Destination already exists: {new_path}")

            if not dry_run:
                old_path.rename(new_path)

            success_count += 1
            logger.debug(f"Renamed {old_path.name} -> {new_name}")

        except Exception as e:
            failure_count += 1
            errors.append((old_path, str(e)))
            logger.error(f"Error renaming {old_path}: {e}")

    return OperationResult(
        success_count=success_count,
        failure_count=failure_count,
        total_count=total,
        errors=errors,
        success=(failure_count == 0)
    )


# ============================================================================
# Utility Functions
# ============================================================================

def format_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 MB", "350 KB")

    Example:
        >>> format_size(1536000)
        '1.46 MB'
        >>> format_size(500)
        '500 B'
    """
    value = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if value < 1024.0:
            if unit == 'B':
                return f"{int(value)} {unit}"
            formatted = f"{value:.2f}".rstrip('0').rstrip('.')
            return f"{formatted} {unit}"
        value /= 1024.0
    formatted = f"{value:.2f}".rstrip('0').rstrip('.')
    return f"{formatted} PB"


def validate_paths(paths: List[Path]) -> tuple[List[Path], List[tuple[Path, str]]]:
    """
    Validate a list of file paths.

    Args:
        paths: List of file paths to validate

    Returns:
        Tuple of (valid_paths, errors) where errors is list of (path, reason)

    Example:
        >>> paths = [Path("/exists.txt"), Path("/missing.txt")]
        >>> valid, errors = validate_paths(paths)
        >>> print(f"Valid: {len(valid)}, Errors: {len(errors)}")
    """
    valid = []
    errors = []

    for path in paths:
        try:
            _require_regular_file(path)
        except (OSError, ValueError) as e:
            errors.append((path, str(e)))
        else:
            valid.append(path)

    return valid, errors


# ============================================================================
# Testing
# ============================================================================

def _test_operations():
    """Test function for standalone testing."""
    import tempfile

    print("Testing FileHerder Operations...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        print("\n1. Creating test files...")
        test_files = []
        for i in range(5):
            test_file = tmp_path / f"test_{i}.txt"
            test_file.write_text(f"Test content {i}")
            test_files.append(test_file)
        print(f"   ✓ Created {len(test_files)} test files")

        print("\n2. Testing copy_files...")
        dest_dir = tmp_path / "copies"
        result = copy_files(test_files, dest_dir, dry_run=True)
        print(f"   ✓ [DRY RUN] Would copy {result.success_count} files")

        print("\n3. Testing move_files...")
        move_dest = tmp_path / "moved"
        result = move_files(test_files[:2], move_dest, dry_run=True)
        print(f"   ✓ [DRY RUN] Would move {result.success_count} files")

        print("\n4. Testing delete_files_safe...")
        result = delete_files_safe(
            test_files,
            require_confirmation=False,
            dry_run=True
        )
        print(f"   ✓ [DRY RUN] Would delete {result.success_count} files")

        print("\n5. Testing rename_files_batch...")
        rename_map = {
            test_files[0]: "renamed_0.txt",
            test_files[1]: "renamed_1.txt"
        }
        result = rename_files_batch(rename_map, dry_run=True)
        print(f"   ✓ [DRY RUN] Would rename {result.success_count} files")

        print("\n6. Testing format_size...")
        test_sizes = [100, 1500, 1500000, 1500000000]
        for size in test_sizes:
            formatted = format_size(size)
            print(f"   {size} bytes -> {formatted}")

    print("\nAll tests complete!")


if __name__ == "__main__":
    _test_operations()
