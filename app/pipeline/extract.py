"""Stage 2: SI/BL text -> ShipmentFields.

Field-label normalization happens here: the SI and BL often label the same
field differently (e.g. "Port of Loading" vs "Load Port"), so the model is
asked to align by meaning, not by header text, before compare.py ever runs.
"""
from app.llm_client import call_json
from app.schema import ShipmentFields

SYSTEM_PROMPT = """You extract 7 shipment fields from a shipping document (an SI or a
draft Bill of Lading). The document may label a field differently than the field
name below -- match by meaning, not by header text (e.g. "Load Port", "POL", and
"Port of Loading" all mean port_of_loading).

Fields to extract:
- shipper
- consignee
- notify_party
- port_of_loading
- port_of_discharge
- container_count (keep the raw value as written, e.g. "6 x 40'HC")
- gross_weight_kg (keep the raw value as written, e.g. "131,058 KG")

If a field is not present in the document, use null for it. Respond with JSON
only, no prose, in this exact shape:
{"shipper": ..., "consignee": ..., "notify_party": ..., "port_of_loading": ...,
 "port_of_discharge": ..., "container_count": ..., "gross_weight_kg": ...}"""


def extract_fields(doc_text: str) -> ShipmentFields:
    """Extract the 7 shipment fields from raw SI or BL text via one LLM call."""
    result = call_json(SYSTEM_PROMPT, doc_text)
    return ShipmentFields(**result)
