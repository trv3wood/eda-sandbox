from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tlm_agent.graph.extract import (
    extract_document_graph,
    normalize_spec_response,
    produce_spec_graph,
)
from tlm_agent.extractors import extract_project
from tlm_agent.graph.finalize import align_cross_source
from tlm_agent.graph.schema import entity, relationship, validate_graph
from tlm_agent.io import dump_yaml, load_json


class GraphExtractTest(unittest.TestCase):
    def test_markdown_chunks_are_stable_and_source_located(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            spec = project / "spec.md"
            spec.write_text(
                "# DMA\n\nTransfers data.\ncontinued.\n\n## Errors\n\n"
                "The DMA reports `fatal_error`.\n",
                encoding="utf-8",
            )
            first_tree, first_units = extract_document_graph(project, [spec])
            second_tree, second_units = extract_document_graph(project, [spec])

            self.assertEqual(first_tree, second_tree)
            self.assertEqual(first_units, second_units)
            transfer = next(
                item for item in first_units
                if item["text"] == "Transfers data.\ncontinued."
            )
            self.assertEqual(transfer["section_path"], ["DMA"])
            self.assertEqual(transfer["locator"], "lines:3-4")

    def test_llm_response_requires_valid_spans_and_endpoints(self) -> None:
        units = [{
            "id": "txt-1",
            "text": "DMA reports fatal_error.",
            "source_path": "spec.md",
            "source_digest": "abc",
            "locator": "line:1",
            "section_path": ["DMA"],
        }]
        response = {
            "entities": [{
                "local_id": "error",
                "type": "Error",
                "name": "fatal_error",
                "description": "A fatal DMA error.",
                "properties": {},
                "source_spans": [{
                    "text_unit_id": "txt-1",
                    "start": 12,
                    "end": 23,
                }],
            }],
            "relationships": [],
        }
        entities, relationships = normalize_spec_response(
            response,
            units,
            model="fixture",
            response_digest="response",
        )
        self.assertEqual(entities[0]["source_refs"][0]["text"], "fatal_error")
        self.assertEqual(relationships, [])

        response["entities"][0]["source_spans"][0]["end"] = 100
        with self.assertRaisesRegex(ValueError, "invalid source span"):
            normalize_spec_response(
                response,
                units,
                model="fixture",
                response_digest="response",
            )

    def test_spec_producer_batches_and_reuses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            spec = project / "spec.md"
            spec.write_text("# DMA\n\nDMA transfers bytes.\n", encoding="utf-8")
            dump_yaml(project / "manifest.yaml", {
                "schema_version": 1,
                "name": "dma",
                "target_top": "dma",
                "reference_top": "dma",
                "documents": ["spec.md"],
                "registers": [],
                "rtl": [],
                "testbench": [],
                "eda_compile": {
                    "sources": [],
                    "include_dirs": [],
                    "defines": [],
                },
                "graph": {
                    "spec_extraction": {
                        "model": "fixture-model",
                        "base_url": "http://fixture.invalid/v1",
                        "batch_max_chars": 1000,
                    }
                },
            })
            extract_project(project, run_tools=False)
            calls = []

            class Completions:
                def create(self, **kwargs):
                    calls.append(kwargs)
                    assert kwargs["response_format"] == {"type": "json_object"}
                    units = json.loads(kwargs["messages"][1]["content"])
                    unit = units[0]
                    response = {
                        "entities": [{
                            "local_id": "section",
                            "type": "Section",
                            "name": unit["text"],
                            "description": unit["text"],
                            "properties": {},
                            "source_spans": [{
                                "text_unit_id": unit["id"],
                                "start": 0,
                                "end": len(unit["text"]),
                            }],
                        }],
                        "relationships": [],
                    }
                    message = types.SimpleNamespace(
                        content=json.dumps(response)
                    )
                    return types.SimpleNamespace(
                        choices=[types.SimpleNamespace(message=message)],
                        model="fixture-model",
                        system_fingerprint="fixture-fingerprint",
                    )

            class OpenAI:
                def __init__(self, **_kwargs):
                    self.chat = types.SimpleNamespace(
                        completions=Completions()
                    )

            fake = types.ModuleType("openai")
            fake.OpenAI = OpenAI
            with patch.dict(sys.modules, {"openai": fake}):
                first = produce_spec_graph(project)
                second = produce_spec_graph(project)

            self.assertEqual(first["status"], "passed")
            self.assertEqual(second["response_digest"], first["response_digest"])
            self.assertEqual(len(calls), first["batch_count"])
            entities = load_json(
                project / ".systemc-agent/graph/manifest.json"
            )["producers"]["spec"]["entity_count"]
            self.assertGreater(entities, 0)

    def test_exact_alignment_rejects_ambiguous_short_names(self) -> None:
        provenance = {"extractor": "fixture", "source_backed": True}
        refs = [{
            "source_path": "spec.md",
            "source_digest": "abc",
            "locator": "line:1",
            "text": "DMA uses status and dma_core.",
        }]
        spec = entity(
            entity_type="Requirement",
            name="dma_core",
            source_refs=refs,
            provenance=provenance,
        )
        rtl = [
            entity(
                entity_type="Module",
                name="dma_core",
                source_refs=refs,
                provenance=provenance,
            ),
            entity(
                entity_type="Signal",
                name="status",
                source_refs=refs,
                provenance=provenance,
                identity={"kind": "Signal", "scope": "a", "name": "status"},
            ),
            entity(
                entity_type="Signal",
                name="status",
                source_refs=refs,
                provenance=provenance,
                identity={"kind": "Signal", "scope": "b", "name": "status"},
            ),
        ]
        edges = align_cross_source([spec], rtl)
        self.assertEqual([edge["type"] for edge in edges], ["CORRESPONDS_TO"])

    def test_graph_validation_catches_orphan_instance(self) -> None:
        provenance = {"extractor": "fixture", "source_backed": False}
        module = entity(
            entity_type="Module", name="top", provenance=provenance
        )
        instance = entity(
            entity_type="Instance",
            name="u_child",
            properties={"is_top": False},
            provenance=provenance,
        )
        of_edge = relationship(
            relation_type="OF",
            source_id=instance["id"],
            target_id=module["id"],
            provenance=provenance,
        )
        result = validate_graph([module, instance], [of_edge])
        self.assertTrue(any("orphaned" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
