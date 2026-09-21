"""Save the page image of every scanned document, so a person (or a vision model) can read it.

This is what the pipeline's vision step is shown when Tesseract is not sure. Run stage1_parse.py
first; it says which documents are scans.

    python reference/claude-as-llm/render_scans.py    # writes results/claude-llm/scans/*.png
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from loader import Inbox

from app.paths import inbox_source
from app.pipeline.read_document import load_document

parsed = ROOT / "results" / "claude-llm" / "parsed.json"
if not parsed.exists():
    sys.exit("Run stage1_parse.py first.")

out_dir = ROOT / "results" / "claude-llm" / "scans"
out_dir.mkdir(parents=True, exist_ok=True)
inbox = Inbox(inbox_source())

for path, record in json.loads(parsed.read_text(encoding="utf-8")).items():
    if record["kind"] != "scanned":
        continue
    document = load_document(inbox, path)
    for page, (png, _mime) in enumerate(document.images, start=1):
        name = f"{Path(path).stem}{'' if len(document.images) == 1 else f'_p{page}'}.png"
        (out_dir / name).write_bytes(png)
        print(out_dir / name)
