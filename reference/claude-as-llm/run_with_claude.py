"""Run the real pipeline with Claude standing in for the model.

Only the three model calls are replaced, each by a lookup into the answers in answers/:

  classify.call_json       -> answers/classify.json  (one entry per email)
  extract.extract_fields   -> the keyword parser's value where it is sure, else answers/extract.json
  extract._vision_extract  -> answers/extract.json   (read from the page image)

Everything else is the project's own code: reading documents, Tesseract OCR with confidence, the
keyword parser, validation, comparison and the human-review rules. No network call is made.

    python reference/claude-as-llm/run_with_claude.py                 # writes to results/claude-llm/
    python reference/claude-as-llm/run_with_claude.py --into-results  # writes to results/ itself

By default the run writes into results/claude-llm/, so it cannot touch your real results. With
--into-results it behaves like POST /run (a fresh run): the old results.jsonl is copied to a .bak
first if it holds a real verdict, then replaced.

The pipeline stops with an AssertionError if it ever asks the "model" something the answer sheets
do not cover, instead of quietly returning nothing.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--into-results", action="store_true", help="write into results/ (replaces the current run)")
parser.add_argument("--results-dir", type=Path, default=ROOT / "results" / "claude-llm", help="where to write otherwise")
args = parser.parse_args()

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")  # for TESSERACT_CMD and INBOX_SOURCE

import app.paths as paths

if not args.into_results:
    args.results_dir.mkdir(parents=True, exist_ok=True)
    paths.RESULTS_DIR = args.results_dir  # results_file() reads this at call time

import app.llm_client as llm
from app.pipeline import classify, extract
from app.pipeline.ocr import keyword_hits, text_lines
from app.pipeline.validate import validate_field
from app.schema import ShipmentFields

CLASSIFY = json.loads((HERE / "answers" / "classify.json").read_text(encoding="utf-8"))
EXTRACT = json.loads((HERE / "answers" / "extract.json").read_text(encoding="utf-8"))
CALLS = {"classification": 0, "text_fields": [], "vision_fields": []}


def _who():
    email_id = llm._email_id.get()
    stage = llm._processing_stage.get()
    role = {"si_extraction": "SI", "bl_extraction": "BL"}.get(stage)
    return email_id, stage, role


def claude_call_json(system, user, max_tokens=None):
    email_id, stage, _ = _who()
    assert stage == "classification", f"unexpected model call in stage {stage!r} for {email_id}"
    CALLS["classification"] += 1
    return dict(CLASSIFY[email_id])


def claude_extract_fields(doc_text):
    """The parser reads what it is sure of; only the fields it could not settle are answered."""
    email_id, _stage, role = _who()
    hits = keyword_hits(text_lines(doc_text))
    out = {}
    for name in extract.FIELD_NAMES:
        hit = hits.get(name)
        if hit and hit.confidence >= 80 and validate_field(name, hit.value) is None:
            out[name] = hit.value
            continue
        key = f"{email_id}/{role}"
        if key not in EXTRACT or name not in EXTRACT[key]:
            raise AssertionError(f"the pipeline asked the model for {key} {name} and there is no answer")
        out[name] = EXTRACT[key][name]
        CALLS["text_fields"].append((email_id, role, name))
    return ShipmentFields(**out)


def claude_vision(images, names):
    email_id, _stage, role = _who()
    key = f"{email_id}/{role}"
    reply = {}
    for name in names:
        if key not in EXTRACT or name not in EXTRACT[key]:
            raise AssertionError(f"the pipeline asked vision for {key} {name} and there is no answer")
        reply[name] = EXTRACT[key][name]
        CALLS["vision_fields"].append((email_id, role, name))
    return reply


classify.call_json = claude_call_json
extract.extract_fields = claude_extract_fields
extract._vision_extract = claude_vision

import app.main as main
from app import run_state

result = main._do_run(None, False)  # the same function POST /run calls
run_state.end()

print(json.dumps(result, indent=1))
print("model calls answered from the sheets:")
print("  classifications:", CALLS["classification"])
print("  fields on text documents:", len(CALLS["text_fields"]), "in", len({(e, r) for e, r, _ in CALLS["text_fields"]}), "documents")
print("  fields read from page images:", len(CALLS["vision_fields"]), "in", len({(e, r) for e, r, _ in CALLS["vision_fields"]}), "documents")
