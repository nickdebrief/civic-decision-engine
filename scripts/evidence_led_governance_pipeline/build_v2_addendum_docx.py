"""Compatibility import surface for older publication scripts.

The implementation moved to ``build.py``, ``parser.py``, ``model.py``,
``validator.py``, ``themes/handbook.py``, and ``renderers/docx_renderer.py``.
"""

from build import build_document, next_version
from parser import normalise_structure, parse_code_title

__all__ = [
    "build_document",
    "next_version",
    "normalise_structure",
    "parse_code_title",
]
