export const CATEGORY = {
  BL_COMPARISON: { label: "BL comparison" },
  SI_REQUEST: { label: "SI request" },
  INVOICE_QUERY: { label: "Invoice query" },
  GENERAL: { label: "General" },
  SPAM: { label: "Spam" },
};

export const CATEGORY_ORDER = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"];

export const FIELDS = [
  ["shipper", "Shipper"],
  ["consignee", "Consignee"],
  ["notify_party", "Notify party"],
  ["port_of_loading", "Port of loading"],
  ["port_of_discharge", "Port of discharge"],
  ["container_count", "Container count"],
  ["gross_weight_kg", "Gross weight (kg)"],
];

export const REASON = {
  unreadable: "Document unreadable",
  missing_attachment: "Attachment missing",
  ambiguous_attachment: "More than one candidate attachment",
  missing_value: "Value needs checking",
  wrong_doc_type: "Wrong document type",
  low_confidence: "Low confidence",
  processing_error: "Processing failed",
};

export const SOURCE = { text: "read from text", ocr: "read by OCR", ocr_llm: "read by OCR and LLM", vision: "read by vision model" };

export function categoryLabel(category) {
  return CATEGORY[category]?.label ?? category ?? "Unknown";
}

export function formatConfidence(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "\u2014";
}

export function formatTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function plural(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}
