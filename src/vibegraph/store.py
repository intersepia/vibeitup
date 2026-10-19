"""Persistent, tree-shaped graph store.

Design decisions
----------------
* One graph = one small JSON file. Nodes and edges are plain objects, so the
  format stays easy to inspect, diff, back up and hand-edit.
* The graph is a *forest*: one permanent root plus any number of detached
  trees. Every non-root node has at most one incoming edge (a parent), which
  keeps the layout a tidy left-to-right tree and makes "delete an edge"
  lossless: removing an edge only detaches a subtree, it never deletes nodes.
* Node ids are unique case-insensitively. Existing ids are resolved tolerantly
  (e.g. "API" finds "api"), which keeps agent calls forgiving.
* Every mutation is written atomically before it becomes visible in memory.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_ID_LEN = 80
MAX_LABEL_LEN = 160
MAX_NOTE_LEN = 4000
MAX_EDGE_LABEL_LEN = 120


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class GraphError(ValueError):
    """A user-correctable graph error. The MCP layer turns this into ToolError."""


@dataclass
class Mutation:
    """Result of a write operation: a consistent snapshot plus a change event."""

    state: dict[str, Any]
    change: dict[str, Any]
    changed: bool = True


class GraphStore:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        root_id: str = "root",
        root_label: str = "Root",
    ) -> None:
        self.path = Path(path).expanduser()
        self.root_id = self._clean_id(root_id, what="root id")
        self._lock = threading.RLock()
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: list[dict[str, Any]] = []
        self._revision = 0
        self._updated_at = utc_now()
        self._load(root_label=root_label)

    # ------------------------------------------------------------------ load
    def _load(self, *, root_label: str) -> None:
        if not self.path.exists():
            now = utc_now()
            self._nodes = {self.root_id: self._new_node(self.root_id, root_label or self.root_id, "", now)}
            self._edges = []
            self._revision = 0
            self._updated_at = now
            try:
                self._write(self._file_data(self._nodes, self._edges, self._revision, now))
            except OSError as exc:
                raise GraphError(f"Could not create graph file {self.path}: {exc}") from exc
            return

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GraphError(f"Could not read graph file {self.path}: {exc}") from exc

        # An empty file is treated as "not initialised yet", not as corruption.
        if not raw.strip():
            now = utc_now()
            self._nodes = {self.root_id: self._new_node(self.root_id, root_label or self.root_id, "", now)}
            self._edges = []
            self._revision = 0
            self._updated_at = now
            self._write(self._file_data(self._nodes, self._edges, self._revision, now))
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GraphError(
                f"Graph file {self.path} is not valid JSON (line {exc.lineno}, column {exc.colno}: "
                f"{exc.msg}). It was left untouched; fix it or move it away, then restart."
            ) from exc

        try:
            nodes, edges, revision, updated_at = self._parse(data)
        except GraphError as exc:
            raise GraphError(f"Invalid graph file {self.path}: {exc}") from exc

        self._nodes = nodes
        self._edges = edges
        self._revision = revision
        self._updated_at = updated_at

    def _parse(
        self, data: Any
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, str]:
        if not isinstance(data, dict):
            raise GraphError("top-level value must be a JSON object")
        if data.get("schema") != SCHEMA_VERSION:
            raise GraphError(
                f"expected \"schema\": {SCHEMA_VERSION}, got {data.get('schema')!r}"
            )
        raw_nodes = data.get("nodes")
        raw_edges = data.get("edges", [])
        if not isinstance(raw_nodes, list):
            raise GraphError("\"nodes\" must be a list")
        if not isinstance(raw_edges, list):
            raise GraphError("\"edges\" must be a list")

        nodes: dict[str, dict[str, Any]] = {}
        folded: dict[str, str] = {}
        for item in raw_nodes:
            if not isinstance(item, dict):
                raise GraphError("every node must be an object")
            try:
                nid = self._clean_id(item.get("id"), what="node id")
                label = self._clean_label(item.get("label") or nid)
                note = self._clean_note(item.get("note") or "")
            except GraphError as exc:
                raise GraphError(f"node {item.get('id')!r}: {exc}") from exc
            if nid in nodes:
                raise GraphError(f"duplicate node id {nid!r}")
            key = nid.casefold()
            if key in folded:
                raise GraphError(
                    f"node ids {folded[key]!r} and {nid!r} only differ by letter case"
                )
            created_at = item.get("created_at") if isinstance(item.get("created_at"), str) else utc_now()
            nodes[nid] = {"id": nid, "label": label, "note": note, "created_at": created_at}
            folded[key] = nid

        root = data.get("root", self.root_id)
        if not isinstance(root, str) or root not in nodes:
            raise GraphError(f"root node {root!r} is missing from \"nodes\"")
        if root != self.root_id:
            # Follow the file, but keep the configured root id as an alias only
            # when it does not exist. This makes the store self-describing.
            self.root_id = root

        edges: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        incoming: dict[str, str] = {}
        for item in raw_edges:
            if not isinstance(item, dict):
                raise GraphError("every edge must be an object")
            source = item.get("source")
            target = item.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                raise GraphError("every edge needs string \"source\" and \"target\"")
            if source not in nodes or target not in nodes:
                raise GraphError(f"edge {source!r} -> {target!r} references a missing node")
            if source == target:
                raise GraphError(f"edge {source!r} -> {target!r} is a self-loop")
            if target == root:
                raise GraphError("the root cannot be the target of an edge")
            if target in incoming:
                raise GraphError(
                    f"node {target!r} has more than one parent ({incoming[target]!r}, {source!r}); "
                    "VibeGraph is a tree, not a DAG"
                )
            if (source, target) in seen_pairs:
                raise GraphError(f"duplicate edge {source!r} -> {target!r}")
            try:
                label = self._clean_edge_label(item.get("label") or "")
            except GraphError as exc:
                raise GraphError(f"edge {source!r} -> {target!r}: {exc}") from exc
            created_at = item.get("created_at") if isinstance(item.get("created_at"), str) else utc_now()
            edges.append(
                {"source": source, "target": target, "label": label, "created_at": created_at}
            )
            seen_pairs.add((source, target))
            incoming[target] = source

        # Detect cycles (a single-parent constraint makes this a simple walk).
        parent = {edge["target"]: edge["source"] for edge in edges}
        for start in nodes:
            seen: set[str] = set()
            cursor = start
            while cursor in parent:
                if cursor in seen:
                    raise GraphError(f"cycle detected at node {cursor!r}")
                seen.add(cursor)
                cursor = parent[cursor]

        revision = data.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise GraphError("\"revision\" must be a non-negative integer")
        updated_at = data.get("updated_at")
        if not isinstance(updated_at, str):
            updated_at = utc_now()
        return nodes, edges, revision, updated_at

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _now() -> str:
        return utc_now()

    @staticmethod
    def _clean_id(value: Any, *, what: str = "node id") -> str:
        if not isinstance(value, str):
            raise GraphError(f"{what} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise GraphError(f"{what} must not be empty")
        if len(cleaned) > MAX_ID_LEN:
            raise GraphError(f"{what} is too long (max {MAX_ID_LEN} characters)")
        if any(ord(ch) < 32 for ch in cleaned):
            raise GraphError(f"{what} must not contain control characters")
        return cleaned

    @staticmethod
    def _clean_label(value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise GraphError("label must be a string")
        cleaned = value.strip()
        if len(cleaned) > MAX_LABEL_LEN:
            raise GraphError(f"label is too long (max {MAX_LABEL_LEN} characters)")
        return cleaned

    @staticmethod
    def _clean_note(value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise GraphError("note must be a string")
        cleaned = value.strip()
        if len(cleaned) > MAX_NOTE_LEN:
            raise GraphError(f"note is too long (max {MAX_NOTE_LEN} characters)")
        return cleaned

    @staticmethod
    def _clean_edge_label(value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise GraphError("edge label must be a string")
        cleaned = value.strip()
        if len(cleaned) > MAX_EDGE_LABEL_LEN:
            raise GraphError(f"edge label is too long (max {MAX_EDGE_LABEL_LEN} characters)")
        return cleaned

    def _new_node(self, node_id: str, label: str, note: str, now: str) -> dict[str, Any]:
        clean_label = self._clean_label(label) or node_id
        return {
            "id": node_id,
            "label": clean_label,
            "note": self._clean_note(note),
            "created_at": now,
        }

    @staticmethod
    def _new_edge(source: str, target: str, label: str, now: str) -> dict[str, Any]:
        return {"source": source, "target": target, "label": label, "created_at": now}

    @staticmethod
    def _parent_map(edges: list[dict[str, Any]]) -> dict[str, str]:
        return {edge["target"]: edge["source"] for edge in edges}

    @staticmethod
    def _children_map(edges: list[dict[str, Any]]) -> dict[str, list[str]]:
        children: dict[str, list[str]] = {}
        for edge in edges:
            children.setdefault(edge["source"], []).append(edge["target"])
        return children

    def _resolve(self, nodes: dict[str, dict[str, Any]], value: Any) -> str | None:
        cleaned = self._clean_id(value)
        if cleaned in nodes:
            return cleaned
        folded = cleaned.casefold()
        for node_id in nodes:
            if node_id.casefold() == folded:
                return node_id
        return None

    def _suggest(self, value: str) -> str:
        ids = list(self._nodes)
        candidates = difflib.get_close_matches(value, ids, n=3, cutoff=0.55)
        if not candidates:
            folded = value.casefold()
            candidates = [node_id for node_id in ids if folded in node_id.casefold()][:3]
        if not candidates:
            return ""
        return " Closest ids: " + ", ".join(repr(c) for c in candidates) + "."

    def _require(
        self, nodes: dict[str, dict[str, Any]], value: Any, *, role: str = "node"
    ) -> str:
        resolved = self._resolve(nodes, value)
        if resolved is None:
            raw = value.strip() if isinstance(value, str) else str(value)
            raise GraphError(f"{role.capitalize()} {raw!r} not found.{self._suggest(raw)}")
        return resolved

    @staticmethod
    def _ancestors(node_id: str, edges: list[dict[str, Any]]) -> set[str]:
        parent = {edge["target"]: edge["source"] for edge in edges}
        result: set[str] = set()
        cursor = parent.get(node_id)
        while cursor is not None and cursor not in result:
            result.add(cursor)
            cursor = parent.get(cursor)
        return result

    @staticmethod
    def _subtree_ids(node_id: str, edges: list[dict[str, Any]]) -> list[str]:
        children = GraphStore._children_map(edges)
        result: list[str] = []
        stack = [node_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            result.append(current)
            stack.extend(reversed(children.get(current, [])))
        return result

    # ------------------------------------------------------------ persistence
    def _file_data(
        self,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        revision: int,
        updated_at: str,
    ) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "revision": revision,
            "updated_at": updated_at,
            "root": self.root_id,
            "nodes": [dict(node) for node in nodes.values()],
            "edges": [dict(edge) for edge in edges],
        }

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    def _commit(
        self,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        change: dict[str, Any],
        *,
        changed: bool = True,
    ) -> Mutation:
        with self._lock:
            if changed:
                revision = self._revision + 1
                updated_at = self._now()
                data = self._file_data(nodes, edges, revision, updated_at)
                try:
                    self._write(data)
                except OSError as exc:
                    raise GraphError(f"Could not save {self.path}: {exc}") from exc
                self._nodes = nodes
                self._edges = edges
                self._revision = revision
                self._updated_at = updated_at

            state = self._snapshot_locked()
            event = dict(change)
            event.setdefault("revision", self._revision)
            return Mutation(state=state, change=event, changed=changed)

    # -------------------------------------------------------------- snapshots
    def _snapshot_locked(self) -> dict[str, Any]:
        nodes = [dict(node) for node in self._nodes.values()]
        edges = [dict(edge) for edge in self._edges]
        return {
            "schema": SCHEMA_VERSION,
            "revision": self._revision,
            "updated_at": self._updated_at,
            "root": self.root_id,
            "nodes": nodes,
            "edges": edges,
            "stats": self._compute_stats(self._nodes, self._edges),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _compute_stats(
        self, nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, int]:
        parent = self._parent_map(edges)
        children = self._children_map(edges)
        roots = [node_id for node_id in nodes if node_id not in parent]
        depth: dict[str, int] = {}
        for root in roots:
            stack = [(root, 0)]
            while stack:
                current, level = stack.pop()
                if current in depth or current not in nodes:
                    continue
                depth[current] = level
                for child in reversed(children.get(current, [])):
                    stack.append((child, level + 1))

        connected: set[str] = set()
        stack = [self.root_id] if self.root_id in nodes else []
        while stack:
            current = stack.pop()
            if current in connected or current not in nodes:
                continue
            connected.add(current)
            stack.extend(children.get(current, []))

        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "depth": max(depth.values(), default=0),
            "components": len(roots),
            "detached_trees": max(0, len(roots) - (1 if self.root_id in nodes else 0)),
            "connected_nodes": len(connected),
            "detached_nodes": max(0, len(nodes) - len(connected)),
        }

    # ---------------------------------------------------------------- writes
    def add_edge(self, source: str, target: str, label: str = "") -> Mutation:
        """Attach ``target`` as a child of ``source``.

        Missing nodes are created. If the target already has another parent it
        is moved (with its whole subtree), preserving every node.
        """
        source_raw = self._clean_id(source, what="source")
        target_raw = self._clean_id(target, what="target")
        edge_label = self._clean_edge_label(label)

        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            now = self._now()
            created: list[str] = []

            source_id = self._resolve(nodes, source_raw)
            if source_id is None:
                source_id = source_raw
                nodes[source_id] = self._new_node(source_id, source_id, "", now)
                created.append(source_id)
                if source_id != self.root_id:
                    edges.append(self._new_edge(self.root_id, source_id, "", now))

            target_id = self._resolve(nodes, target_raw)
            if target_id is None:
                target_id = target_raw
                nodes[target_id] = self._new_node(target_id, target_id, "", now)
                created.append(target_id)

            if target_id == self.root_id:
                raise GraphError(
                    "The root has no parent and cannot be a target. Pick another target, "
                    "or use graph_set_parent to move a node under an existing one."
                )
            if source_id == target_id:
                raise GraphError("Source and target must be different nodes.")

            if target_id in self._ancestors(source_id, edges):
                raise GraphError(
                    f"Cannot add {source_id} -> {target_id}: {target_id} is already an ancestor of "
                    f"{source_id}, so this would create a cycle. If you meant to move {source_id} "
                    f"under {target_id}, use graph_set_parent(node_id={source_id}, parent_id={target_id})."
                )

            existing_index = next(
                (i for i, edge in enumerate(edges) if edge["target"] == target_id), None
            )
            previous_parent: str | None = None
            previous_label: str | None = None
            changed = False
            action = "edge_added"

            if existing_index is not None:
                existing = edges[existing_index]
                previous_parent = existing["source"]
                previous_label = existing["label"]
                if previous_parent == source_id:
                    if edge_label and existing["label"] != edge_label:
                        edges[existing_index] = {**existing, "label": edge_label}
                        changed = True
                        action = "edge_updated"
                    else:
                        action = "noop"
                else:
                    edges.pop(existing_index)
                    edges.append(self._new_edge(source_id, target_id, edge_label, now))
                    changed = True
                    action = "parent_changed"
            else:
                edges.append(self._new_edge(source_id, target_id, edge_label, now))
                changed = True

            if created:
                changed = True
                if action == "noop":
                    action = "edge_added"

            edge = next((e for e in edges if e["target"] == target_id), None)
            subtree_size = len(self._subtree_ids(target_id, edges))
            if not changed:
                change = {
                    "action": "noop",
                    "source": source_id,
                    "target": target_id,
                    "edge": dict(edge) if edge else None,
                    "message": f"Edge {source_id} -> {target_id} already exists; nothing changed.",
                }
                return self._commit(nodes, edges, change, changed=False)

            if action == "parent_changed":
                message = (
                    f"Moved {target_id} from under {previous_parent} to under {source_id}. "
                    f"The whole subtree ({subtree_size} nodes) was preserved."
                )
            elif action == "edge_updated":
                message = f"Updated the label of {source_id} -> {target_id}."
            else:
                message = f"Added edge {source_id} -> {target_id}."
            if created:
                message += " Created node(s): " + ", ".join(created) + "."
            if previous_parent and action != "parent_changed":
                message += f" Previous parent: {previous_parent}."

            change = {
                "action": action,
                "source": source_id,
                "target": target_id,
                "edge": dict(edge) if edge else None,
                "nodes_created": created,
                "previous_parent": previous_parent,
                "previous_label": previous_label,
                "subtree_size": subtree_size,
                "message": message,
            }
            return self._commit(nodes, edges, change)

    def add_node(
        self,
        node_id: str,
        *,
        label: str = "",
        note: str = "",
        parent: str | None = None,
    ) -> Mutation:
        """Create a node (or update/attach an existing one)."""
        raw_id = self._clean_id(node_id)
        clean_label = self._clean_label(label)
        clean_note = self._clean_note(note)
        parent_raw = None if parent is None or not str(parent).strip() else self._clean_id(parent)

        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            now = self._now()
            resolved = self._resolve(nodes, raw_id)
            if resolved is None:
                if raw_id.casefold() == self.root_id.casefold():
                    raise GraphError(f"The root node {self.root_id!r} already exists.")
                parent_id = self.root_id
                if parent_raw is not None:
                    parent_id = self._require(nodes, parent_raw, role="parent")
                if parent_id == raw_id:
                    raise GraphError("A node cannot be its own parent.")
                node = self._new_node(raw_id, clean_label or raw_id, clean_note, now)
                nodes[raw_id] = node
                edges.append(self._new_edge(parent_id, raw_id, "", now))
                change = {
                    "action": "node_added",
                    "node": dict(node),
                    "parent": parent_id,
                    "message": f"Added node {raw_id} under {parent_id}.",
                }
                return self._commit(nodes, edges, change)

            node_id_resolved = resolved
            old = dict(nodes[node_id_resolved])
            new = dict(old)
            fields: list[str] = []
            if clean_label and clean_label != old["label"]:
                new["label"] = clean_label
                fields.append("label")
            if clean_note and clean_note != old["note"]:
                new["note"] = clean_note
                fields.append("note")
            if fields:
                nodes[node_id_resolved] = new

            moved = False
            old_parent = self._parent_map(edges).get(node_id_resolved)
            if parent_raw is not None:
                parent_id = self._require(nodes, parent_raw, role="parent")
                if node_id_resolved == self.root_id:
                    raise GraphError("The root node cannot be moved.")
                if parent_id == node_id_resolved:
                    raise GraphError("A node cannot be its own parent.")
                if node_id_resolved in self._ancestors(parent_id, edges):
                    raise GraphError(
                        f"Cannot move {node_id_resolved} under its own descendant {parent_id}."
                    )
                if old_parent != parent_id:
                    edges = [edge for edge in edges if edge["target"] != node_id_resolved]
                    edges.append(self._new_edge(parent_id, node_id_resolved, "", now))
                    moved = True
                elif not fields:
                    return self._commit(
                        nodes,
                        edges,
                        {
                            "action": "noop",
                            "node": new,
                            "parent": old_parent,
                            "message": f"Node {node_id_resolved} already exists; nothing changed.",
                        },
                        changed=False,
                    )

            if not fields and not moved:
                return self._commit(
                    nodes,
                    edges,
                    {
                        "action": "noop",
                        "node": new,
                        "parent": old_parent,
                        "message": f"Node {node_id_resolved} already exists; nothing changed.",
                    },
                    changed=False,
                )

            if moved:
                action = "parent_changed"
                message = (
                    f"Node {node_id_resolved} now belongs to {nodes_parent(edges, node_id_resolved)}."
                )
            else:
                action = "node_updated"
                message = f"Updated {node_id_resolved} ({', '.join(fields)})."
            change = {
                "action": action,
                "node": dict(nodes[node_id_resolved]),
                "fields": fields,
                "parent": self._parent_map(edges).get(node_id_resolved),
                "message": message,
            }
            return self._commit(nodes, edges, change)

    def set_parent(self, node_id: str, parent_id: str, label: str = "") -> Mutation:
        """Make ``parent_id`` the direct parent of ``node_id`` (moving its subtree)."""
        node_raw = self._clean_id(node_id)
        parent_raw = self._clean_id(parent_id)
        edge_label = self._clean_edge_label(label)

        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            now = self._now()
            node = self._require(nodes, node_raw)
            parent = self._require(nodes, parent_raw, role="parent")
            if node == self.root_id:
                raise GraphError("The root node has no parent and cannot be moved.")
            if node == parent:
                raise GraphError("A node cannot be its own parent.")
            if node in self._ancestors(parent, edges):
                raise GraphError(
                    f"Cannot move {node} under its own descendant {parent} — that would create a cycle."
                )

            old_edge = next((edge for edge in edges if edge["target"] == node), None)
            old_parent = old_edge["source"] if old_edge else None
            if old_parent == parent:
                if edge_label and old_edge and old_edge["label"] != edge_label:
                    edges = [
                        {**edge, "label": edge_label} if edge["target"] == node else edge
                        for edge in edges
                    ]
                    change = {
                        "action": "edge_updated",
                        "node": node,
                        "parent": parent,
                        "message": f"Updated the label of {parent} -> {node}.",
                    }
                    return self._commit(nodes, edges, change)
                return self._commit(
                    nodes,
                    edges,
                    {
                        "action": "noop",
                        "node": node,
                        "parent": parent,
                        "message": f"{node} already belongs to {parent}; nothing changed.",
                    },
                    changed=False,
                )

            if old_edge is not None:
                edges.remove(old_edge)
            edges.append(self._new_edge(parent, node, edge_label, now))
            subtree_size = len(self._subtree_ids(node, edges))
            change = {
                "action": "parent_changed",
                "node": node,
                "old_parent": old_parent,
                "parent": parent,
                "subtree_size": subtree_size,
                "message": (
                    f"Moved {node} from under {old_parent or 'no parent'} to under {parent}. "
                    f"The whole subtree ({subtree_size} nodes) was preserved."
                ),
            }
            return self._commit(nodes, edges, change)

    def update_node(
        self, node_id: str, *, label: str | None = None, note: str | None = None
    ) -> Mutation:
        """Rename a node or change its note (without touching its position)."""
        if label is None and note is None:
            raise GraphError("Pass at least one of label or note.")
        new_label = None if label is None else self._clean_label(label)
        if label is not None and not new_label:
            raise GraphError("Label must not be empty. Use graph_delete_node to remove a node.")
        new_note = None if note is None else self._clean_note(note)

        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            node = self._require(nodes, node_id)
            current = dict(nodes[node])
            fields: list[str] = []
            if new_label is not None and new_label != current["label"]:
                current["label"] = new_label
                fields.append("label")
            if new_note is not None and new_note != current["note"]:
                current["note"] = new_note
                fields.append("note")
            if not fields:
                return self._commit(
                    nodes,
                    edges,
                    {
                        "action": "noop",
                        "node": current,
                        "message": f"Node {node} is already up to date.",
                    },
                    changed=False,
                )
            nodes[node] = current
            change = {
                "action": "node_updated",
                "node": current,
                "fields": fields,
                "message": f"Updated {node} ({', '.join(fields)}).",
            }
            return self._commit(nodes, edges, change)

    def delete_edge(self, source: str, target: str) -> Mutation:
        """Remove a parent->child edge. All nodes stay in the graph."""
        with self._lock:
            source_raw = self._clean_id(source, what="source")
            target_raw = self._clean_id(target, what="target")
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            source_id = self._require(nodes, source_raw, role="source")
            target_id = self._require(nodes, target_raw, role="target")
            index = next(
                (
                    i
                    for i, edge in enumerate(edges)
                    if edge["source"] == source_id and edge["target"] == target_id
                ),
                None,
            )
            if index is None:
                outgoing = [
                    edge["target"] for edge in edges if edge["source"] == source_id
                ]
                hint = (
                    " Outgoing edges from "
                    f"{source_id}: {', '.join(outgoing)}."
                    if outgoing
                    else f" {source_id} has no outgoing edges."
                )
                raise GraphError(f"Edge {source_id} -> {target_id} not found.{hint}")

            removed = edges.pop(index)
            subtree_size = len(self._subtree_ids(target_id, edges))
            change = {
                "action": "edge_removed",
                "source": source_id,
                "target": target_id,
                "edge": dict(removed),
                "nodes_removed": 0,
                "detached_nodes": subtree_size,
                "detached_root": target_id,
                "message": (
                    f"Removed edge {source_id} -> {target_id}. No nodes were deleted; "
                    f"{subtree_size} node(s) now form a detached subtree under {target_id}."
                ),
            }
            return self._commit(nodes, edges, change)

    def delete_node(self, node_id: str, *, mode: str = "reparent") -> Mutation:
        """Delete one node. Default mode keeps its descendants (reparents them)."""
        mode_clean = (mode or "reparent").strip().lower()
        if mode_clean not in {"reparent", "cascade"}:
            raise GraphError("mode must be 'reparent' (default) or 'cascade'.")

        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            node = self._require(nodes, node_id)
            if node == self.root_id:
                raise GraphError("The root node cannot be deleted.")
            parent = self._parent_map(edges).get(node)
            children = self._children_map(edges).get(node, [])

            if mode_clean == "cascade":
                doomed = set(self._subtree_ids(node, edges))
                kept_edges = [
                    edge
                    for edge in edges
                    if edge["source"] not in doomed and edge["target"] not in doomed
                ]
                for doomed_id in doomed:
                    nodes.pop(doomed_id, None)
                removed_count = len(doomed)
                change = {
                    "action": "node_removed",
                    "node": node,
                    "mode": "cascade",
                    "deleted_nodes": sorted(doomed),
                    "nodes_removed": removed_count,
                    "message": (
                        f"Deleted {node} and its entire subtree ({removed_count} nodes). "
                        "This was explicit cascade mode."
                    ),
                }
                return self._commit(nodes, kept_edges, change)

            new_edges: list[dict[str, Any]] = []
            promoted: list[str] = []
            for edge in edges:
                if edge["target"] == node:
                    continue  # incoming edge disappears with the node
                if edge["source"] == node:
                    promoted.append(edge["target"])
                    if parent is not None:
                        new_edges.append({**edge, "source": parent})
                    # Without a parent the children become detached roots.
                else:
                    new_edges.append(edge)
            nodes.pop(node)
            if parent is not None:
                message = (
                    f"Deleted {node}; its {len(promoted)} direct child(ren) were reattached to "
                    f"{parent}. No descendants were lost."
                )
            else:
                message = (
                    f"Deleted detached root {node}; its {len(promoted)} direct child(ren) became "
                    "detached roots. No descendants were lost."
                )
            change = {
                "action": "node_removed",
                "node": node,
                "mode": "reparent",
                "parent": parent,
                "promoted_children": promoted,
                "nodes_removed": 1,
                "message": message,
            }
            return self._commit(nodes, new_edges, change)

    def reset(self, *, confirm: bool = False) -> Mutation:
        """Remove everything except the root node. Requires confirm=True."""
        if confirm is not True:
            raise GraphError(
                "Refusing to reset the graph without confirm=true. Ask the user first; "
                "this removes every node except the root."
            )
        with self._lock:
            root = dict(self._nodes[self.root_id])
            removed_nodes = max(0, len(self._nodes) - 1)
            removed_edges = len(self._edges)
            if removed_nodes == 0 and removed_edges == 0:
                return self._commit(
                    copy.deepcopy(self._nodes),
                    copy.deepcopy(self._edges),
                    {
                        "action": "noop",
                        "message": "The graph is already empty (only the root exists).",
                    },
                    changed=False,
                )
            nodes = {self.root_id: root}
            edges: list[dict[str, Any]] = []
            change = {
                "action": "graph_reset",
                "nodes_removed": removed_nodes,
                "edges_removed": removed_edges,
                "message": (
                    f"Reset the graph: removed {removed_nodes} node(s) and {removed_edges} "
                    "edge(s). The root was kept."
                ),
            }
            return self._commit(nodes, edges, change)

    # ----------------------------------------------------------------- reads
    def read(self, node_id: str | None = None, max_depth: int | None = None) -> dict[str, Any]:
        if max_depth is not None:
            if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
                raise GraphError("max_depth must be an integer >= 0.")
            if max_depth > 100:
                raise GraphError("max_depth is limited to 100.")
        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            revision = self._revision
            updated_at = self._updated_at
            stats = self._compute_stats(nodes, edges)

        parent = self._parent_map(edges)
        children = self._children_map(edges)
        roots = [nid for nid in nodes if nid not in parent]

        def make_tree(current: str, level: int) -> dict[str, Any]:
            node = nodes[current]
            kids = children.get(current, [])
            item: dict[str, Any] = {
                "id": node["id"],
                "label": node["label"],
                "note": node["note"],
                "children": [],
            }
            if max_depth is None or level < max_depth:
                item["children"] = [make_tree(child, level + 1) for child in kids]
            elif kids:
                item["children"] = []
                item["child_count"] = len(kids)
                item["truncated"] = True
            return item

        base = {
            "revision": revision,
            "updated_at": updated_at,
            "stats": stats,
            "root": self.root_id,
        }

        if node_id is not None:
            node = self._require(nodes, node_id)
            path_ids: list[str] = []
            cursor: str | None = node
            while cursor is not None:
                path_ids.append(cursor)
                cursor = parent.get(cursor)
            path_ids.reverse()
            component_root = path_ids[0] if path_ids else node
            base.update(
                {
                    "node": make_tree(node, 0),
                    "parent": parent.get(node),
                    "path": [
                        {"id": nid, "label": nodes[nid]["label"]} for nid in path_ids
                    ],
                    "component_root": component_root,
                    "subtree_size": len(self._subtree_ids(node, edges)),
                }
            )
            return base

        base.update(
            {
                "tree": make_tree(self.root_id, 0),
                "detached": [make_tree(root, 0) for root in roots if root != self.root_id],
            }
        )
        return base

    def search(self, query: str, limit: int = 20) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise GraphError("Search query must not be empty.")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise GraphError("limit must be an integer.")
        limit = max(1, min(limit, 50))
        needle = query.strip().casefold()

        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            edges = copy.deepcopy(self._edges)
            revision = self._revision

        parent = self._parent_map(edges)
        matches: list[dict[str, Any]] = []
        for node_id, node in nodes.items():
            haystack = f"{node_id}\n{node['label']}\n{node['note']}".casefold()
            if needle not in haystack:
                continue
            path_ids: list[str] = []
            cursor: str | None = node_id
            guard = 0
            while cursor is not None and guard <= len(nodes):
                path_ids.append(cursor)
                cursor = parent.get(cursor)
                guard += 1
            path_ids.reverse()
            exact = node_id.casefold() == needle or node["label"].casefold() == needle
            starts = node_id.casefold().startswith(needle) or node["label"].casefold().startswith(needle)
            matches.append(
                {
                    "id": node_id,
                    "label": node["label"],
                    "note": node["note"][:240],
                    "path": path_ids,
                    "depth": max(0, len(path_ids) - 1),
                    "subtree_size": len(self._subtree_ids(node_id, edges)),
                    "_rank": 0 if exact else 1 if starts else 2,
                }
            )
        matches.sort(key=lambda item: (item["_rank"], item["depth"], item["id"].casefold()))
        total = len(matches)
        for item in matches:
            item.pop("_rank", None)
        hint = ""
        if not matches:
            suggestions = difflib.get_close_matches(
                query.strip(), [node["label"] for node in nodes.values()], n=3, cutoff=0.55
            )
            if suggestions:
                hint = "Similar labels: " + ", ".join(repr(s) for s in suggestions)
        return {
            "query": query.strip(),
            "matches": matches[:limit],
            "total_matches": total,
            "truncated": total > limit,
            "hint": hint,
            "revision": revision,
        }


def nodes_parent(edges: list[dict[str, Any]], node_id: str) -> str | None:
    """Small helper used in messages (kept module-level to avoid a re-scan in methods)."""
    for edge in edges:
        if edge["target"] == node_id:
            return edge["source"]
    return None
