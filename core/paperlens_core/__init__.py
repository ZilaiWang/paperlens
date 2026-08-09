"""PaperLens: evidence-grounded academic paper reading."""

from .config import Settings
from .version import __version__

__all__ = ["Settings", "__version__"]

# Persisted component schema versions evolve independently of package releases.
SCHEMA_VERSION = "documentir-v3.0"
PARSER_VERSION = "parser-v3.0"
GLOSSARY_VERSION = "glossary-v0.1"
