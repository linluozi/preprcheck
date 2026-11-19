"""preprcheck: pre-PR duplicate check against upstream git history."""

__version__ = "0.1.0"
__all__ = ["audit", "parse_unified_diff"]

from .audit import audit
from .diffparse import parse_unified_diff
