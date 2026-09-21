"""Claude's extraction answers for the documents the keyword parser could not fully read.

These are the 36 documents (of 250) that had at least one field the parser was not sure of, read
by eye from the document text or, for the 6 scans, from the page image (see render_scans.py).
A field the document does not actually state is null: nothing is guessed, and the pipeline sends
the email to a person. The other 212 documents were read entirely by the parser, with no model.
The 2 corrupt PDFs cannot be read by anyone and are not here.

    python reference/claude-as-llm/build_extract_answers.py      # writes answers/extract.json
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "answers" / "extract.json"
F = ["shipper", "consignee", "notify_party", "port_of_loading", "port_of_discharge"]

# ---- 20 block-layout PDFs: the label is on its own line, the name on the next --------------
# [shipper, consignee, notify_party, port_of_loading, port_of_discharge]
BLOCK = {
    "059": ["APRIL FINE PAPER TRADING", "BALL & DOGGETT AUSTRALIA PTY LTD", "PACIFIC OFFICE (M) SDN BHD", "BUATAN, INDONESIA", "FREMANTLE, AUSTRALIA"],
    "160": ["APRIL FINE PAPER TRADING", "KTP CO., LTD", "KTP CO., LTD", "PORT KLANG (WESTPORT), MALAYSIA", "APAPA, NIGERIA"],
    "208": ["APRIL FAR EAST (M) SDN BHD", "CERIEX", "CERIEX", "RUGAO/NANTONG/SHANGHAI, CHINA", "FREMANTLE, AUSTRALIA"],
    "273": ["ASIA PACIFIC PAPERBOARD TRADING PTE LTD", "KPP-ANTALIS (SINGAPORE) PTE. LTD.", "INTERNATIONAL FOREST PRODUCTS LLC", "RUGAO/NANTONG/SHANGHAI, CHINA", "CONAKRY, GUINEA"],
    "313": ["APRIL FINE PAPER TRADING", "KPP-ANTALIS (SINGAPORE) PTE. LTD.", "KPP-ANTALIS (SINGAPORE) PTE. LTD.", "RUGAO/NANTONG/SHANGHAI, CHINA", "HOCHIMINH CITY, VIETNAM"],
    "351": ["APRIL FINE PAPER TRADING (MIDDLE EAST) FZE", "KTP CO., LTD", "KTP CO., LTD", "PORT KLANG (WESTPORT), MALAYSIA", "ASHDOD, ISRAEL"],
    "407": ["APRIL FINE PAPER TRADING", "NAGAPPA EXPORTS", "NAGAPPA EXPORTS", "NHAVA SHEVA, INDIA", "YANGON, MYANMAR"],
    "411": ["APRIL FAR EAST (M) SDN BHD", "VITAL SOLUTIONS PTE. LTD.", "VITAL SOLUTIONS PTE. LTD.", "PORT KLANG (WESTPORT), MALAYSIA", "NEW YORK, US"],
    "434": ["APRIL FINE PAPER TRADING (MIDDLE EAST) FZE", "TOPKOPY MIDDLE EAST FZE", "TOPKOPY MIDDLE EAST FZE", "NHAVA SHEVA, INDIA", "BUSAN, SOUTH KOREA"],  # SI
    "499": ["APRIL FINE PAPER TRADING (MIDDLE EAST) FZE", "TOPKOPY MIDDLE EAST FZE", "TOPKOPY MIDDLE EAST FZE", "PORT KLANG (WESTPORT), MALAYSIA", "HOCHIMINH CITY, VIETNAM"],
}

ANS = {}
for n, vals in BLOCK.items():
    row = dict(zip(F, vals))
    ANS[f"email_{n}/SI"] = dict(row)
    ANS[f"email_{n}/BL"] = dict(row)
# the one pair whose BL says something different from its SI: port of discharge
ANS["email_434/BL"]["port_of_discharge"] = "CEBU, PHILIPPINES"

# ---- text files that are not the document they should be, or have blank / placeholder values -
NULLS_7 = {f: None for f in F + ["container_count", "gross_weight_kg"]}
ANS["email_501/BL"] = dict(NULLS_7)                      # a commercial invoice, not a BL
for n in ("502", "503", "504", "505"):                   # packing lists / certificates of origin
    ANS[f"email_{n}/BL"] = {"notify_party": None, "port_of_loading": None, "port_of_discharge": None,
                            "container_count": None, "gross_weight_kg": None}
ANS["email_516/SI"] = {"gross_weight_kg": None}          # "N/A"
ANS["email_517/SI"] = {"port_of_loading": None, "port_of_discharge": None}   # "____MT", "TBA"
ANS["email_518/SI"] = {"port_of_discharge": None, "gross_weight_kg": None}   # "N/A", "____MT"
ANS["email_519/SI"] = {"shipper": None, "container_count": None}             # left blank
ANS["email_520/SI"] = {"consignee": None}                                     # left blank

# ---- 6 scanned PDFs, read from the page images (all 7 fields each) -------------------------
def scan(shipper, consignee, notify, pol, pod, containers, weight):
    return {"shipper": shipper, "consignee": consignee, "notify_party": notify,
            "port_of_loading": pol, "port_of_discharge": pod, "container_count": containers, "gross_weight_kg": weight}

s512 = scan("APRIL FAR EAST (M) SDN BHD", "AL GURG STATIONERY LLC", "AL GURG STATIONERY LLC",
            "NHAVA SHEVA, INDIA", "TUTICORIN, INDIA", "6 x 40'HC", "128,544 KG")
s513 = scan("APRIL FINE PAPER TRADING", "KPP-ANTALIS (SINGAPORE) PTE. LTD.", "EAST BRIGHT FZ-LLC",
            "NHAVA SHEVA, INDIA", "VALPARAISO, CHILE", "10 x 40'HC", "237,750 KG")
s514 = scan("ASIA PACIFIC PAPERBOARD TRADING PTE LTD", "EAST BRIGHT FZ-LLC", "EAST BRIGHT FZ-LLC",
            "NANTONG, CHINA", "GDANSK, POLAND", "1 x 20'FCL", "22,825 KG")
for n, s in (("512", s512), ("513", s513), ("514", s514)):
    ANS[f"email_{n}/SI"] = dict(s)
    ANS[f"email_{n}/BL"] = dict(s)

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(ANS, indent=1), encoding="utf-8")
print("answers for", len(ANS), "documents;", sum(len(v) for v in ANS.values()), "field values")
