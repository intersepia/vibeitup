import json
import tempfile
import unittest
from pathlib import Path

from vibegraph.store import GraphError, GraphStore


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "graph.json"
        self.store = GraphStore(self.path, root_label="Root")

    def tearDown(self):
        self.tmp.cleanup()

    def test_initializes_root_and_is_idempotent(self):
        state = self.store.snapshot()
        self.assertEqual(state["root"], "root")
        self.assertEqual(state["stats"]["nodes"], 1)
        self.assertEqual(state["stats"]["edges"], 0)
        self.assertEqual(state["nodes"][0]["label"], "Root")
        self.assertTrue(self.path.exists())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["root"], "root")

        reloaded = GraphStore(self.path)
        self.assertEqual(reloaded.snapshot()["stats"]["nodes"], 1)
        self.assertEqual(reloaded.snapshot()["revision"], 0)

    def test_add_edge_creates_nodes_and_persists(self):
        mutation = self.store.add_edge("a", "b")
        self.assertTrue(mutation.changed)
        self.assertEqual(mutation.change["action"], "edge_added")
        self.assertEqual(set(mutation.change["nodes_created"]), {"a", "b"})
        self.assertEqual(mutation.state["stats"]["nodes"], 3)
        self.assertEqual(mutation.state["stats"]["edges"], 2)
        self.assertEqual(mutation.state["stats"]["depth"], 2)

        reloaded = GraphStore(self.path)
        state = reloaded.snapshot()
        self.assertEqual({n["id"] for n in state["nodes"]}, {"root", "a", "b"})
        self.assertEqual(
            {(e["source"], e["target"]) for e in state["edges"]},
            {("root", "a"), ("a", "b")},
        )

    def test_add_edge_reparents_target_with_whole_subtree(self):
        self.store.add_edge("a", "b")
        self.store.add_edge("b", "c")
        self.store.add_edge("x", "b")
        state = self.store.snapshot()
        ids = {node["id"] for node in state["nodes"]}
        self.assertEqual(ids, {"root", "a", "b", "c", "x"})
        edges = {(e["source"], e["target"]) for e in state["edges"]}
        self.assertIn(("x", "b"), edges)
        self.assertIn(("b", "c"), edges)
        self.assertNotIn(("a", "b"), edges)
        self.assertEqual(self.store.read()["stats"]["connected_nodes"], 5)

    def test_add_edge_cycle_is_rejected(self):
        self.store.add_edge("a", "b")
        with self.assertRaises(GraphError):
            self.store.add_edge("b", "a")
        with self.assertRaises(GraphError):
            self.store.set_parent("a", "b")

    def test_set_parent_moves_subtree(self):
        self.store.add_edge("a", "b")
        self.store.add_edge("b", "c")
        mutation = self.store.set_parent("b", "root")
        self.assertEqual(mutation.change["action"], "parent_changed")
        self.assertEqual(mutation.change["subtree_size"], 2)
        state = self.store.snapshot()
        edges = {(e["source"], e["target"]) for e in state["edges"]}
        self.assertIn(("root", "b"), edges)
        self.assertIn(("b", "c"), edges)
        self.assertNotIn(("a", "b"), edges)
        self.assertEqual(state["stats"]["nodes"], 4)

    def test_delete_edge_keeps_all_nodes(self):
        self.store.add_edge("a", "b")
        self.store.add_edge("b", "c")
        revision = self.store.snapshot()["revision"]
        mutation = self.store.delete_edge("a", "b")
        self.assertGreater(mutation.state["revision"], revision)
        self.assertEqual(mutation.change["nodes_removed"], 0)
        self.assertEqual(mutation.change["detached_nodes"], 2)
        state = self.store.snapshot()
        self.assertEqual(state["stats"]["nodes"], 4)
        self.assertEqual(state["stats"]["detached_trees"], 1)
        self.assertEqual(state["stats"]["detached_nodes"], 2)
        self.assertIn("b", {node["id"] for node in state["nodes"]})
        self.assertIn("c", {node["id"] for node in state["nodes"]})
        read = self.store.read()
        self.assertEqual(read["detached"][0]["id"], "b")
        self.assertEqual(read["detached"][0]["children"][0]["id"], "c")

    def test_reattach_detached_subtree(self):
        self.store.add_edge("a", "b")
        self.store.add_edge("b", "c")
        self.store.delete_edge("a", "b")
        self.assertEqual(self.store.snapshot()["stats"]["detached_trees"], 1)
        mutation = self.store.add_edge("a", "b")
        self.assertEqual(mutation.state["stats"]["detached_trees"], 0)
        self.assertEqual(mutation.state["stats"]["connected_nodes"], 4)

    def test_delete_node_reparents_children(self):
        self.store.add_edge("a", "b")
        self.store.add_edge("b", "c")
        mutation = self.store.delete_node("b")
        self.assertEqual(mutation.change["mode"], "reparent")
        self.assertEqual(mutation.change["promoted_children"], ["c"])
        state = self.store.snapshot()
        self.assertEqual({node["id"] for node in state["nodes"]}, {"root", "a", "c"})
        edges = {(e["source"], e["target"]) for e in state["edges"]}
        self.assertEqual(edges, {("root", "a"), ("a", "c")})

    def test_delete_node_cascade_is_explicit(self):
        self.store.add_edge("a", "b")
        self.store.add_edge("b", "c")
        mutation = self.store.delete_node("b", mode="cascade")
        self.assertEqual(mutation.change["mode"], "cascade")
        self.assertEqual(set(mutation.change["deleted_nodes"]), {"b", "c"})
        self.assertEqual(self.store.snapshot()["stats"]["nodes"], 2)

    def test_root_cannot_be_target_moved_or_deleted(self):
        self.store.add_edge("a", "b")
        with self.assertRaises(GraphError):
            self.store.add_edge("a", "root")
        with self.assertRaises(GraphError):
            self.store.set_parent("root", "a")
        with self.assertRaises(GraphError):
            self.store.delete_node("root")

    def test_add_node_is_idempotent_and_moves(self):
        created = self.store.add_node("thing", label="Thing", note="hello", parent="root")
        self.assertEqual(created.change["action"], "node_added")
        same = self.store.add_node("THING")
        self.assertFalse(same.changed)
        self.assertEqual(same.change["action"], "noop")
        updated = self.store.add_node("thing", label="Renamed", note="new")
        self.assertTrue(updated.changed)
        self.assertEqual(updated.state["nodes"][-1]["label"], "Renamed")
        self.assertEqual(updated.state["nodes"][-1]["note"], "new")
        self.store.add_edge("group", "container")
        moved = self.store.add_node("thing", parent="container")
        self.assertEqual(moved.change["action"], "parent_changed")
        parents = {
            edge["target"]: edge["source"] for edge in moved.state["edges"]
        }
        self.assertEqual(parents["thing"], "container")

    def test_update_node_and_clear_note(self):
        self.store.add_node("x", label="X", note="note")
        self.store.update_node("x", label="Ex", note="")
        node = next(n for n in self.store.snapshot()["nodes"] if n["id"] == "x")
        self.assertEqual(node["label"], "Ex")
        self.assertEqual(node["note"], "")
        with self.assertRaises(GraphError):
            self.store.update_node("x", label="")
        with self.assertRaises(GraphError):
            self.store.update_node("x")

    def test_case_insensitive_resolution(self):
        self.store.add_edge("API", "Client")
        self.store.add_edge("api", "Worker")
        state = self.store.snapshot()
        self.assertEqual(
            sorted(n["id"] for n in state["nodes"]),
            ["API", "Client", "Worker", "root"],
        )
        self.assertEqual(self.store.read("client")["node"]["id"], "Client")
        with self.assertRaises(GraphError):
            self.store.update_node("unknown-node", label="x")

    def test_reset_requires_confirm_and_keeps_root(self):
        self.store.add_edge("a", "b")
        with self.assertRaises(GraphError):
            self.store.reset()
        mutation = self.store.reset(confirm=True)
        self.assertEqual(mutation.change["action"], "graph_reset")
        state = self.store.snapshot()
        self.assertEqual(state["stats"]["nodes"], 1)
        self.assertEqual(state["nodes"][0]["id"], "root")
        self.assertEqual(state["nodes"][0]["label"], "Root")
        self.assertFalse(self.store.reset(confirm=True).changed)

    def test_noop_does_not_increment_revision(self):
        self.store.add_edge("a", "b")
        revision = self.store.snapshot()["revision"]
        mutation = self.store.add_edge("a", "b")
        self.assertFalse(mutation.changed)
        self.assertEqual(mutation.state["revision"], revision)

    def test_max_depth_read_and_search(self):
        self.store.add_edge("a", "b")
        self.store.add_edge("b", "c")
        shallow = self.store.read(max_depth=1)
        self.assertEqual(shallow["tree"]["children"][0]["id"], "a")
        self.assertTrue(shallow["tree"]["children"][0]["truncated"])
        found = self.store.search("C")
        self.assertEqual(found["total_matches"], 1)
        self.assertEqual(found["matches"][0]["id"], "c")
        self.assertEqual(found["matches"][0]["depth"], 3)
        with self.assertRaises(GraphError):
            self.store.search("")

    def test_invalid_json_is_not_overwritten(self):
        self.path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(GraphError):
            GraphStore(self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ not json")

    def test_two_parents_are_rejected_on_load(self):
        data = {
            "schema": 1,
            "revision": 1,
            "root": "root",
            "nodes": [
                {"id": "root", "label": "Root", "note": "", "created_at": "2026-01-01T00:00:00Z"},
                {"id": "a", "label": "a", "note": "", "created_at": "2026-01-01T00:00:00Z"},
                {"id": "b", "label": "b", "note": "", "created_at": "2026-01-01T00:00:00Z"},
                {"id": "c", "label": "c", "note": "", "created_at": "2026-01-01T00:00:00Z"},
            ],
            "edges": [
                {"source": "root", "target": "b", "label": "", "created_at": "2026-01-01T00:00:00Z"},
                {"source": "b", "target": "a", "label": "", "created_at": "2026-01-01T00:00:00Z"},
                {"source": "c", "target": "a", "label": "", "created_at": "2026-01-01T00:00:00Z"},
            ],
        }
        self.path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(GraphError):
            GraphStore(self.path)


if __name__ == "__main__":
    unittest.main()
