"""VibeGraph — a tiny tree-shaped graph store with an MCP server and a live viewer."""

__version__ = "0.1.0"

from .store import GraphError, GraphStore, Mutation

__all__ = ["GraphError", "GraphStore", "Mutation", "__version__"]
