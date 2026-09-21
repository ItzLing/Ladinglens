"""Claude's classification answers: one decision per email wording found in the inbox.

Each rule below is a wording that was actually read in data/inbox/. The inbox is heavily
templated (520 emails, 43 distinct wordings, about 26 kinds). Every email must match exactly one
rule; if any email matches none this script stops instead of guessing, so a new kind of email
shows up as an error rather than a silent wrong label.

    python reference/claude-as-llm/build_classify_answers.py     # writes answers/classify.json

The confidence is the model's own certainty, as classify.py asks for it. It is deliberately
lower where the call is a judgement: 0.6 for "please send the draft BL" (no attachments, but
the same thread family as the real BL checks) and 0.7 for the "submit SI & AED" reminder.
"""
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "answers" / "classify.json"


def core(body: str) -> str:
    body = re.sub(r"WARNING: This email originated outside[^\n]*\n*", "", body)
    body = re.sub(r"^\s*(Dear|Hi|Hello)[^\n]*\n+", "", body.strip())
    return re.sub(r"\s+", " ", re.split(r"\n\s*\n", body.strip())[0]).strip()


def find(pattern, text, default=""):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else default


def words(text, limit=20):
    return " ".join(text.split()[:limit])


def si_summary(email, c):
    body = re.sub(r"\s+", " ", email.get("body", ""))
    oc = find(r"Shipping instruction for ([\w\-]+)", c)
    pol = find(r"POL:\s*(.+?)\s+POD:", body)
    pod = find(r"POD:\s*(.+?)\s+(?:Shipper|Consignee|Notify|Container)", body)
    return f"Sends the shipping instruction for {oc}, loading at {pol} and discharging at {pod}."


RULES = [
    # (name, regex on the first paragraph, category, confidence, summary(email, core))
    ("bl check with attachments", r"^(Please find attached the shipping instruction and the draft bill of lading|Pls assist to check the draft BL against the SI|Attached are the SI and draft BL for OC)",
     "BL_COMPARISON", 0.98, lambda e, c: "Asks for the attached shipping instruction and draft bill of lading to be checked against each other."),
    ("SI with invoice", r"the SI and the Commercial Invoice", "BL_COMPARISON", 0.9,
     lambda e, c: "Sends the SI with a commercial invoice and asks to confirm the BL; no draft BL is attached."),
    ("SI with packing list", r"the SI and the Packing List", "BL_COMPARISON", 0.9,
     lambda e, c: "Sends the SI with a packing list and asks to confirm the BL; no draft BL is attached."),
    ("SI with certificate of origin", r"the SI and the Certificate of Origin", "BL_COMPARISON", 0.9,
     lambda e, c: "Sends the SI with a certificate of origin and asks to confirm the BL; no draft BL is attached."),
    ("BL still missing", r"the draft BL is still missing", "BL_COMPARISON", 0.95,
     lambda e, c: "Asks to compare the SI and draft BL, but says the draft BL is still missing."),
    ("BL will not open", r"the BL file will not open", "BL_COMPARISON", 0.95,
     lambda e, c: "Sends the SI and a draft BL file that will not open, and asks for advice."),
    ("scanned copies", r"scanned copies \(image only\)", "BL_COMPARISON", 0.95,
     lambda e, c: "Sends scanned image-only copies of the SI and draft BL for checking."),
    ("SI fields blank", r"Some SI fields were left blank", "BL_COMPARISON", 0.95,
     lambda e, c: "Asks to compare the SI and draft BL although the customer left some SI fields blank."),
    ("attachments dropped", r"attachments appear to have been dropped", "BL_COMPARISON", 0.9,
     lambda e, c: "Asks to compare the SI and draft BL, but the attachments appear to have been dropped."),
    ("send the draft BL", r"^Please assist to send the draft BL for", "BL_COMPARISON", 0.6,
     lambda e, c: f"Asks for the draft BL for {find(r'draft BL for ([\w\-]+)', c)} to be sent for checking; nothing is attached."),
    ("shipping instruction sent", r"^Please find Shipping instruction for", "SI_REQUEST", 0.85, si_summary),
    ("GR missing", r"GR is still missing for invoice", "INVOICE_QUERY", 0.96,
     lambda e, c: f"Says the goods receipt is still missing for invoice {find(r'invoice ([\w\-]+)', c)} and asks for it to be posted."),
    ("THC query", r"is the THC / local charge included", "INVOICE_QUERY", 0.96,
     lambda e, c: f"Asks whether the THC or local charge on invoice {find(r'invoice ([\w\-]+)', c)} is included or billed separately."),
    ("D&D charges", r"D&D / detention charges", "INVOICE_QUERY", 0.95,
     lambda e, c: f"Sends detention charges for {find(r'charges for ([\w\-]+)', c)} and asks to confirm the amount before payment."),
    ("cancel invoice", r"Requesting to cancel invoice", "INVOICE_QUERY", 0.95,
     lambda e, c: f"Asks to cancel invoice {find(r'cancel invoice ([\w\-]+)', c)} and reverse the PGI because the booking was amended."),
    ("outstanding BL list", r"list of outstanding BL", "GENERAL", 0.92,
     lambda e, c: "Sends the list of outstanding BLs and asks for the pending items to be actioned."),
    ("submit SI reminder", r"^Reminder: Please submit SI & AED", "GENERAL", 0.7,
     lambda e, c: "Reminds everyone to submit SI and AED for all pending shipments by end of day."),
    ("new year", r"Wishing everyone a happy and prosperous New Year", "GENERAL", 0.95,
     lambda e, c: "Sends New Year greetings and says the office resumes normal operations on 2 January."),
    ("automated billing notice", r"India HSS SD Billing Process for", "GENERAL", 0.9,
     lambda e, c: f"Automated notice that the India HSS SD billing process for {find(r'Process for (.+?) has completed', c)} completed; no action needed."),
    ("berthing report", r"daily berthing report", "GENERAL", 0.92,
     lambda e, c: f"Daily berthing report: vessel {find(r'Vessel (.+?) berthed', c)} berthed on schedule."),
    ("update summary", r"update summary for", "GENERAL", 0.92,
     lambda e, c: f"Sends the update summary for {find(r'update summary for (.+?)\. Loading', c)}: loading completed, documents to follow."),
    ("prize scam", r"selected in our monthly draw", "SPAM", 0.99,
     lambda e, c: "Prize-draw scam asking the reader to claim a gift card through a link."),
    ("limited offer", r"LIMITED TIME OFFER", "SPAM", 0.99,
     lambda e, c: "Marketing spam offering 90% off a logistics automation suite."),
    ("bank officer", r"bank officer with an urgent business proposal", "SPAM", 0.99,
     lambda e, c: "Advance-fee scam asking the reader for bank details."),
    ("package fee", r"package could not be delivered due to unpaid customs fee", "SPAM", 0.99,
     lambda e, c: "Phishing message about an unpaid customs fee for an undelivered package."),
    ("iphone", r"won a brand new iPhone", "SPAM", 0.99,
     lambda e, c: "Scam claiming an iPhone prize and asking for a shipping fee."),
    ("mailbox full", r"mailbox has exceeded its storage limit", "SPAM", 0.99,
     lambda e, c: "Phishing message about a full mailbox asking the reader to verify their account."),
]

answers, used, unmatched = {}, Counter(), []
for path in sorted(glob.glob(str(ROOT / "data" / "inbox" / "*.json"))):
    email = json.load(open(path, encoding="utf-8"))
    c = core(email.get("body", ""))
    for name, pattern, category, confidence, summarise in RULES:
        if re.search(pattern, c):
            summary = words(" ".join(summarise(email, c).split()), 20)
            answers[email["email_id"]] = {"category": category, "confidence": confidence, "summary": summary}
            used[name] += 1
            break
    else:
        unmatched.append((email["email_id"], c[:100]))

if unmatched:
    print("UNMATCHED:", len(unmatched))
    for u in unmatched[:20]:
        print("  ", u)
    sys.exit(1)

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(answers, indent=1), encoding="utf-8")
print("classified", len(answers), "emails")
print("by category:", dict(Counter(a["category"] for a in answers.values())))
for name, n in used.most_common():
    print(f"  {n:4d}  {name}")
