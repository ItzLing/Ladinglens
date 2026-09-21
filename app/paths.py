"""Where things live. Every script imports these, so they cannot drift apart.

    data/inbox/        one JSON per email     } the folder names are fixed by
    data/attachments/  the SI / BL documents  } data/loader.py
    results/           everything a run writes (see results/README.md)
"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RESULTS_DIR = ROOT_DIR / "results"


def inbox_source() -> str:
    """Where to read emails from: INBOX_SOURCE, else data/.

    Either a folder that holds `inbox/` and `attachments/`, or an http(s) URL of
    the hackathon's dataset server. A relative folder is taken from the repo root,
    not from whatever directory the command happened to be run in.
    """
    source = os.environ.get("INBOX_SOURCE") or str(DATA_DIR)
    if source.startswith(("http://", "https://")):
        return source
    path = Path(source)
    return str(path if path.is_absolute() else ROOT_DIR / path)


def results_file(name: str) -> Path:
    """Path of a file inside results/, creating the folder if it is missing."""
    RESULTS_DIR.mkdir(exist_ok=True)
    return RESULTS_DIR / name
