"""The evidence vocabulary must agree everywhere it is repeated: the rules, the schema, the labels the API
and the site show, the public policy document and its Chinese mirror, and the extension's copy of the
query core. A new anchor added to policy.py but not to the schema silently blocks every record that uses
it (that happened with A9)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.policy import ANCHOR_CODES, CORROBORATION_CODES, WEIGHTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CODES = set(ANCHOR_CODES) | set(CORROBORATION_CODES)


def test_schema_enum_matches_policy():
    schema = json.loads((ROOT / "schema/entity.schema.json").read_text(encoding="utf-8"))
    enum = set(schema["$defs"]["evidence"]["properties"]["code"]["enum"])
    assert enum == CODES, f"schema enum vs policy codes: {enum ^ CODES}"


def test_every_code_has_a_weight():
    assert set(WEIGHTS) == CODES


def test_evidence_labels_cover_every_code():
    core = (ROOT / "packages/core/resolve.mjs").read_text(encoding="utf-8")
    block = re.search(r"export const EVIDENCE_LABELS = \{(.*?)\n\};", core, re.S).group(1)
    labelled = set(re.findall(r"^\s*([AB]\d):", block, re.M))
    assert labelled == CODES, f"labels vs policy codes: {labelled ^ CODES}"


def test_policy_documents_list_every_anchor_in_both_languages():
    for doc in ("POLICY.md", "docs/zh/POLICY.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        listed = set(re.findall(r"^\| \*\*(A\d)\*\* \|", text, re.M))
        assert listed == set(ANCHOR_CODES), f"{doc}: {listed ^ set(ANCHOR_CODES)}"


def test_extension_copy_of_the_query_core_is_in_sync():
    core = (ROOT / "packages/core/resolve.mjs").read_bytes()
    ext = (ROOT / "extension/resolve.mjs").read_bytes()
    assert core == ext, "extension/resolve.mjs differs from packages/core/resolve.mjs; copy it over"
