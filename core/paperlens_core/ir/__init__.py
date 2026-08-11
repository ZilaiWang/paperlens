"""DocumentIR vNext (改进方案1 §四 / 改进方案2 §17-18).

The V1 module ``paperlens_core.documents`` remains as a compatibility layer.
This package introduces the next-generation document model:

    SourceVersion
        └── ParseRun (parsing/parse_run.py)
                └── CanonicalDocument
                        └── CanonicalNode
                                ├── Revision
                                └── Provenance

Node identity (``node_id``) is the logical "same paragraph" across parses;
``revision_id`` identifies one concrete parse of that node.  Annotations bind
to ``node_id``, translation binds to ``revision_id`` / ``content_hash``.
"""

from .canonical import (
    CanonicalDocument,
    CanonicalNode,
    NodeType,
    blocks_from_canonical_document,
    canonical_document_from_blocks,
    canonical_node_from_block,
)
from .identity import (
    UserAccount,
    UserProvider,
    Workspace,
    WorkspaceClaim,
    WorkspaceKind,
)
from .provenance import (
    ProvenanceKind,
    ProvenanceRecord,
)
from .revisions import (
    Revision,
    RevisionStatus,
    revision_from_node,
)

__all__ = [
    "CanonicalDocument",
    "CanonicalNode",
    "NodeType",
    "blocks_from_canonical_document",
    "canonical_document_from_blocks",
    "canonical_node_from_block",
    "UserAccount",
    "UserProvider",
    "Workspace",
    "WorkspaceClaim",
    "WorkspaceKind",
    "ProvenanceKind",
    "ProvenanceRecord",
    "Revision",
    "RevisionStatus",
    "revision_from_node",
]
