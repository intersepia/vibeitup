"""MCP server: exposes the tree store as tools and keeps the live viewer in sync."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .store import GraphError, GraphStore, Mutation
from .viewer import EventHub, ViewerError, ViewerServer

LOG = logging.getLogger("vibegraph")

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # MCP Python SDK 1.x
    try:
        from mcp.server.fastmcp import FastMCP as _MCPServer  # type: ignore[assignment]
        from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[assignment]
    except ImportError as exc:  # pragma: no cover - environment problem
        raise SystemExit(
            "The 'mcp' package is required. Install it with: pip install 'mcp>=1.12'"
        ) from exc

_INSTRUCTIONS = """\
VibeGraph is a live, tree-shaped graph that the user watches in a browser.

Model
- The graph always has one root node with id "{root}" (the left edge of the viewer).
- An edge source -> target means "target is a child of source". Each node has at most one parent.
- The graph is a forest only when an edge is deleted: every node stays, and the affected subtree is shown as detached.
- Missing nodes are created automatically by graph_add_edge. A newly created source attaches to the root.

How to translate the user's wording
- "A geht zu B" / "A goes to B" / "A -> B"  =>  graph_add_edge(source="A", target="B")
- "B gehört zu C" / "B belongs to C"        =>  graph_set_parent(node_id="B", parent_id="C")
- "delete the connection A -> B"            =>  graph_delete_edge(source="A", target="B")
  This never deletes nodes: children of B are preserved as a detached subtree.
- "remove node B"                          =>  graph_delete_node(node_id="B")
  The default mode "reparent" keeps B's children and moves them to B's parent.
- If the target already has a parent, graph_add_edge moves it (and its whole subtree) under the new source.
- Cycles are rejected. The root can never be a target, moved, or deleted.

Working style
- Call graph_read before restructuring an unfamiliar graph; it returns the full tree, the root id, stats and the viewer URL.
- Use graph_search to find ids by label or note.
- Prefer short, stable, human-readable node ids such as "api", "auth-service" or "Graph Store".
- After mutations, tell the user what changed and point them to the viewer URL from the tool result.
- Use graph_reset only if the user explicitly asks to clear everything (it requires confirm=true).
"""


def create_mcp_server(
    store: GraphStore,
    hub: EventHub,
    *,
    meta: dict[str, Any],
    get_viewer_url,
):
    instructions = _INSTRUCTIONS.format(root=store.root_id)
    kwargs: dict[str, Any] = {"name": "vibegraph", "instructions": instructions}
    try:
        server = _MCPServer(**kwargs, version=__version__)  # type: ignore[call-arg]
    except TypeError:  # SDK 1.x has no version kwarg
        server = _MCPServer(**kwargs)

    def publish(mutation: Mutation) -> None:
        if not mutation.changed:
            return
        payload = dict(mutation.state)
        payload["change"] = mutation.change
        payload["meta"] = dict(meta)
        hub.publish(payload)

    def result(mutation: Mutation) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "changed": mutation.changed,
            **mutation.change,
            "revision": mutation.state["revision"],
            "stats": mutation.state["stats"],
        }
        url = get_viewer_url()
        if url:
            payload["viewer_url"] = url
        return payload

    def with_url(payload: dict[str, Any]) -> dict[str, Any]:
        url = get_viewer_url()
        if url:
            payload["viewer_url"] = url
        return payload

    def commit(mutation: Mutation) -> dict[str, Any]:
        publish(mutation)
        return result(mutation)

    @server.tool(name="graph_add_edge")
    async def graph_add_edge(source: str, target: str, label: str = "") -> dict[str, Any]:
        """Connect two nodes: target becomes a child of source.

        Use this for "A goes to B" / "A -> B". Missing nodes are created
        automatically (a new source attaches to the root). If target already
        has a parent, it is moved under source together with its whole
        subtree; no node is ever deleted by this tool.

        Args:
            source: Parent node id (created under the root if missing).
            target: Child node id (created if missing; cannot be the root).
            label: Optional short label for the edge, e.g. "calls" or "owns".
        """
        try:
            return commit(store.add_edge(source, target, label))
        except GraphError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="graph_add_node")
    async def graph_add_node(
        node_id: str,
        label: str = "",
        note: str = "",
        parent: str | None = None,
    ) -> dict[str, Any]:
        """Create a node (idempotent) or update/attach an existing one.

        The node is placed under `parent` (default: the root). Existing nodes
        keep their id; non-empty label/note arguments update them, and passing
        a parent moves the node with its whole subtree. Prefer graph_add_edge
        when the user describes a connection.

        Args:
            node_id: Stable id, e.g. "api" or "Graph Store".
            label: Optional display label (defaults to the id).
            note: Optional longer description (markdown-friendly plain text).
            parent: Optional parent id; defaults to the root for new nodes.
        """
        try:
            return commit(store.add_node(node_id, label=label, note=note, parent=parent))
        except GraphError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="graph_set_parent")
    async def graph_set_parent(node_id: str, parent_id: str, label: str = "") -> dict[str, Any]:
        """Make parent_id the direct parent of node_id ("B belongs to C").

        Use this for "B gehört zu C" / "B belongs to C". The node's whole
        subtree moves with it. Both nodes must already exist; the root cannot
        be moved. This never deletes nodes.

        Args:
            node_id: The node that belongs to a parent (cannot be the root).
            parent_id: The new direct parent.
            label: Optional label for the new parent->node edge.
        """
        try:
            return commit(store.set_parent(node_id, parent_id, label))
        except GraphError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="graph_update_node")
    async def graph_update_node(
        node_id: str,
        label: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Rename a node or update its note without changing its position.

        Args:
            node_id: Existing node id.
            label: New non-empty display label (omit to keep the current one).
            note: New note; an empty string clears it (omit to keep it).
        """
        try:
            return commit(store.update_node(node_id, label=label, note=note))
        except GraphError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="graph_delete_edge")
    async def graph_delete_edge(source: str, target: str) -> dict[str, Any]:
        """Delete the connection source -> target. No nodes are ever deleted.

        The target and its entire subtree remain in the graph as a detached
        tree (visible in a dashed box in the viewer). Use this whenever the
        user says "delete the connection", "cut the edge" or similar. To
        remove a node itself, use graph_delete_node.

        Args:
            source: Parent node id of the edge.
            target: Child node id of the edge.
        """
        try:
            return commit(store.delete_edge(source, target))
        except GraphError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="graph_delete_node")
    async def graph_delete_node(node_id: str, mode: str = "reparent") -> dict[str, Any]:
        """Delete one node, preserving its descendants by default.

        mode="reparent" (default) reattaches the node's direct children to its
        parent; no descendants are lost. mode="cascade" permanently deletes the
        whole subtree — only use it when the user explicitly asks to delete
        everything below the node. The root cannot be deleted.

        Args:
            node_id: Existing non-root node id.
            mode: "reparent" (safe default) or "cascade" (destructive).
        """
        try:
            return commit(store.delete_node(node_id, mode=mode))
        except GraphError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="graph_read")
    async def graph_read(
        node_id: str | None = None, max_depth: int | None = None
    ) -> dict[str, Any]:
        """Read the graph as a nested tree (plus detached trees).

        Call this first to discover node ids and structure. Without node_id it
        returns the complete tree rooted at the permanent root, all detached
        trees, stats, revision and the viewer URL. With node_id it returns that
        subtree, its path from the component root, its parent and subtree size.

        Args:
            node_id: Optional node to read instead of the whole graph.
            max_depth: Optional depth limit (0 = only the requested node).
        """
        try:
            payload = store.read(node_id, max_depth)
        except GraphError as exc:
            raise ToolError(str(exc)) from exc
        return with_url(payload)

    @server.tool(name="graph_search")
    async def graph_search(query: str, limit: int = 20) -> dict[str, Any]:
        """Search node ids, labels and notes (case-insensitive substring).

        Returns matches with their path from the component root, depth and
        subtree size. Useful for finding the right id before editing.

        Args:
            query: Text to search for.
            limit: Maximum number of matches (1-50, default 20).
        """
        try:
            payload = store.search(query, limit)
        except GraphError as exc:
            raise ToolError(str(exc)) from exc
        return with_url(payload)

    @server.tool(name="graph_reset")
    async def graph_reset(confirm: bool = False) -> dict[str, Any]:
        """Remove every node except the permanent root. Destructive.

        Only call this when the user explicitly asks to clear the whole graph.
        Requires confirm=true; the root node and its label are kept.

        Args:
            confirm: Must be true to perform the reset.
        """
        try:
            return commit(store.reset(confirm=confirm))
        except GraphError as exc:
            raise ToolError(str(exc)) from exc

    return server


# ------------------------------------------------------------------ CLI mode
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibegraph-mcp",
        description="MCP server for VibeGraph (stdio) plus the live browser viewer.",
    )
    parser.add_argument(
        "--graph",
        default=os.environ.get("VIBEGRAPH_GRAPH", "graph.json"),
        help="Path to graph.json (default: %(default)s)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("VIBEGRAPH_HOST", "127.0.0.1"),
        help="Viewer bind address (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("VIBEGRAPH_PORT", "8787")),
        help="Viewer port; the next free one is used if busy (default: %(default)s)",
    )
    parser.add_argument(
        "--no-viewer",
        action="store_true",
        help="Run MCP only, without starting the HTTP viewer.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


async def _run(args: argparse.Namespace) -> None:
    store = GraphStore(args.graph)
    state = store.snapshot()
    LOG.info(
        "graph: %s (revision %s, %s nodes, %s edges)",
        store.path,
        state["revision"],
        state["stats"]["nodes"],
        state["stats"]["edges"],
    )

    hub = EventHub()
    viewer: ViewerServer | None = None
    viewer_url: str | None = None
    meta: dict[str, Any] = {
        "app": "VibeGraph",
        "version": __version__,
        "demo": False,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    if not args.no_viewer:
        candidate = ViewerServer(store, hub, host=args.host, port=args.port)
        try:
            await candidate.start()
        except ViewerError as exc:
            LOG.warning("viewer disabled: %s", exc)
        else:
            viewer = candidate
            viewer_url = viewer.url
            meta = viewer.meta
            LOG.info("viewer: %s", viewer_url)

    server = create_mcp_server(
        store,
        hub,
        meta=meta,
        get_viewer_url=lambda: viewer_url,
    )
    LOG.info("MCP stdio ready")

    try:
        await server.run_stdio_async()
    finally:
        if viewer is not None:
            await viewer.stop()
        hub.close()


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[vibegraph] %(message)s",
    )
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass
    except GraphError as exc:
        print(f"[vibegraph] {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
