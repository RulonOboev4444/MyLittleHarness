from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.inventory import EXPECTED_SPEC_NAMES, load_inventory
from mylittleharness.projection import build_projection
from tests.test_cli import make_root, write_sample_roadmap


class ProjectionTests(unittest.TestCase):
    def test_projection_rebuild_is_deterministic_and_hashes_readable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            first = build_projection(load_inventory(root))
            second = build_projection(load_inventory(root))

            self.assertEqual(first, second)
            self.assertEqual(first.summary.rebuild_status, "rebuilt-from-inventory")
            self.assertEqual(first.summary.storage_boundary, "none")
            self.assertGreater(first.summary.source_count, 0)
            self.assertEqual(first.summary.readable_source_count, first.summary.hashed_source_count)

            state = first.source_by_path["project/project-state.md"]
            self.assertEqual(len(state.content_hash or ""), 64)
            self.assertGreater(state.line_count, 0)
            self.assertGreater(state.link_count, 0)

    def test_projection_records_links_and_fan_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            projection = build_projection(load_inventory(root))

            docmap_links = [record for record in projection.links if record.target == ".agents/docmap.yaml"]
            self.assertEqual(2, len(docmap_links))
            self.assertTrue(all(record.status == "present" for record in docmap_links))

            docmap_fan_in = [record for record in projection.fan_in if record.target == ".agents/docmap.yaml"]
            self.assertEqual(1, len(docmap_fan_in))
            self.assertEqual(2, docmap_fan_in[0].inbound_count)
            self.assertEqual(("AGENTS.md", "README.md"), docmap_fan_in[0].sources)

    def test_projection_records_lifecycle_relationship_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=False)
            write_sample_roadmap(root)
            projection = build_projection(load_inventory(root))

            node_ids = {node.id for node in projection.relationship_nodes}
            self.assertIn("project/roadmap.md", node_ids)
            self.assertIn("project/roadmap.md#minimal-roadmap-mutation-rail", node_ids)

            dependency_edges = [
                edge
                for edge in projection.relationship_edges
                if edge.source == "project/roadmap.md#minimal-roadmap-mutation-rail"
                and edge.relation == "dependencies"
            ]
            self.assertEqual(1, len(dependency_edges))
            self.assertEqual("project/roadmap.md#roadmap-operationalization-rail", dependency_edges[0].target)
            self.assertEqual("present", dependency_edges[0].status)
            slice_member_edges = [
                edge
                for edge in projection.relationship_edges
                if edge.source == "project/roadmap.md#roadmap-operationalization-rail"
                and edge.relation == "slice_members"
            ]
            self.assertEqual(
                {"project/roadmap.md#roadmap-operationalization-rail", "project/roadmap.md#minimal-roadmap-mutation-rail"},
                {edge.target for edge in slice_member_edges},
            )
            self.assertGreater(projection.summary.relationship_node_count, 0)
            self.assertGreater(projection.summary.relationship_edge_count, 0)

    def test_projection_reports_missing_and_unreadable_source_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            missing = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]
            missing.unlink()
            unreadable = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[1]
            unreadable.write_bytes(b"# Spec\n\xff\n")

            projection = build_projection(load_inventory(root))
            missing_record = projection.source_by_path[f"project/specs/workflow/{EXPECTED_SPEC_NAMES[0]}"]
            unreadable_record = projection.source_by_path[f"project/specs/workflow/{EXPECTED_SPEC_NAMES[1]}"]

            self.assertFalse(missing_record.present)
            self.assertEqual(1, projection.summary.missing_required_count)
            self.assertEqual("decoded with replacement characters", unreadable_record.read_error)
            self.assertIsNone(unreadable_record.content_hash)


if __name__ == "__main__":
    unittest.main()
