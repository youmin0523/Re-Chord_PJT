# Apply the NumPy legacy-alias shim before any submodule can pull in madmom
# or other 2018-era SOTA libraries. Putting the import here makes every
# ``from backend.app.pipeline.X`` carry the shim implicitly — workers and
# API handlers all go through this package.
from . import _numpy_compat  # noqa: F401
