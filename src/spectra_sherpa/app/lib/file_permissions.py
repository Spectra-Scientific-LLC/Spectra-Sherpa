"""Platform-aware file mode handling for local persistence.

POSIX descriptors are restricted to their owner. Windows uses the containing
profile's inherited ACL; POSIX mode bits cannot establish a Windows ACL.
"""

import os


def restrict_file_descriptor(descriptor: int) -> None:
    """Apply owner-only POSIX permissions without calling Unix APIs on Windows."""
    if os.name != "nt":
        os.fchmod(descriptor, 0o600)
