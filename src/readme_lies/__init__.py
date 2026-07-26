"""readme-lies — find claims in your docs that are no longer true.

Your code has tests. Your docs have nothing, so they rot silently: a renamed
script, a moved file, a license badge that outlived its LICENSE file. This
checks the claims a repository can answer about itself, statically.
"""

from __future__ import annotations

__version__ = "0.1.2"

from .core import check, check_document, find_documents
from .model import Finding, Level

__all__ = ["check", "check_document", "find_documents", "Finding", "Level", "__version__"]
