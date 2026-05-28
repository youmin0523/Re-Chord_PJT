"""Storage abstraction — local filesystem (Phase A) vs cloud (Phase B).

Code that needs to persist a job artifact uses ``get_storage()`` instead
of touching the filesystem directly. Phase A returns a ``LocalStorage``
rooted at ``settings.data_dir``; Phase B reads ``STORAGE_BACKEND`` env to
pick one of:

    local            (default)            → on-host filesystem
    r2 / cloudflare  (S3-compatible)       → Cloudflare R2 (egress free)
    s3                                      → AWS S3 (drop-in via boto3)

The interface is intentionally small: ``put`` (write bytes), ``get_url``
(public/presigned URL for download), ``delete``, ``exists``. Anything
fancier (multipart upload, lifecycle rules) belongs in the concrete
backend, not the interface.
"""

from .base import Storage, get_storage
from .local import LocalStorage
from .s3 import S3CompatibleStorage

__all__ = ["Storage", "get_storage", "LocalStorage", "S3CompatibleStorage"]
