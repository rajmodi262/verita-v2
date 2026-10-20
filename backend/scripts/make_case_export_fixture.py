"""Write a Python-signed case export (and a tampered copy) as frontend test fixtures.

    cd backend && uv run python scripts/make_case_export_fixture.py . ../frontend/src/test/fixtures


The browser verifier must agree with the Python one byte for byte, so its test runs on files
the Python side produced: a fresh throwaway Ed25519 key, real evidence from the defend test
case, the offline narrative and its verification report.
"""

import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1])))  # backend dir (for tests.defend.conftest)

from tests.defend.conftest import alert_input  # noqa: E402

from verita.defend.canonical import canonicalize  # noqa: E402
from verita.defend.evidence import build_case_evidence  # noqa: E402
from verita.defend.merkle import MerkleTree  # noqa: E402
from verita.defend.narrative import offline_sentences  # noqa: E402
from verita.defend.signing import Signer, public_pem  # noqa: E402
from verita.defend.verifier import verify  # noqa: E402

out = Path(sys.argv[2])
items = dict(build_case_evidence(42, [alert_input(7)]).items)
sentences = offline_sentences(items)
items["narrative"] = {"version": 1, "mode": "offline", "sentences": sentences}
items["verification"] = verify(sentences, build_case_evidence(42, [alert_input(7)]).items).to_dict()
items["approval"] = {"case_id": 42, "approved_by": "marcus", "approved_at": "2022-09-12T10:00:00+00:00", "unicode": "€ — 😀 דּ", "ratio": 0.1, "big": 1e21, "small": 1e-7}
with tempfile.TemporaryDirectory() as tmp:
    signer = Signer.load_or_create(Path(tmp) / "k.pem")
tree = MerkleTree.build(items)
export = {
    "format": "verita-case-file/1",
    "case_id": 42,
    "title": "fixture",
    "items": items,
    "leaves": tree.leaf_hex(),
    "merkle_root": tree.root,
    "signature": {
        "algorithm": "Ed25519",
        "key_id": signer.key_id,
        "value": signer.sign(42, tree.root),
        "message": f"verita-case-v1:42:{tree.root}",
        "signed_at": "2022-09-12T10:00:00+00:00",
    },
    "public_key_pem": public_pem(signer.public),
}
(out / "case-export.json").write_bytes(canonicalize(export))
tampered = copy.deepcopy(export)
tampered["items"]["EV-TXN-102"]["payload"]["amount_paid"] = 9751.5
(out / "case-export-tampered.json").write_bytes(canonicalize(tampered))
print("root", tree.root)
