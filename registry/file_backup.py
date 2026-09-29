"""
Content-only backup of registry-owned files.

Registry backups (`*.json.previous`) preserve bytes, never Unix metadata. The
API runs non-root (uid 10001) against bind mounts whose files may be owned by
the host user or root, with write access granted by ACL only. Copying owner,
mode, timestamps, or extended attributes (shutil.copy2 / copystat) onto a file
the process does not own fails with EPERM even though the content write
itself is permitted, so backups here depend only on write capability.
"""

import shutil
from pathlib import Path


def backup_file_contents(source: Path, destination: Path) -> None:
    """Overwrite `destination` with the exact bytes of `source`.

    Does not copy owner, group, mode, timestamps, or extended attributes; an
    existing destination is truncated and rewritten in place, keeping its own
    inode and ownership. The destination must be a sibling of the source and
    neither may be a symbolic link, so a backup never writes outside the
    directory of the file it protects. Any failure is raised as OSError for
    the caller's rollback.
    """
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or destination.is_symlink():
        raise OSError("Backup source and destination must not be symbolic links.")
    if source.parent.resolve() != destination.parent.resolve():
        raise OSError("Backup destination must be in the same directory as its source.")
    shutil.copyfile(source, destination)
