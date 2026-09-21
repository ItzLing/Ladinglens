// One interface, two backends. The live one talks to the FastAPI app; the static one
// reads report.json, so the same UI works as a read-only demo with no server.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(fetchFn, url, options) {
  let response;
  try {
    response = await fetchFn(url, options);
  } catch {
    throw new ApiError(0, "Could not reach the server.");
  }
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json()).detail; } catch { /* not JSON */ }
    throw new ApiError(response.status, typeof detail === "string" && detail ? detail : `Request failed (${response.status}).`);
  }
  return response.json();
}

const enc = encodeURIComponent;

function liveApi(fetchFn) {
  const get = (url) => request(fetchFn, url);
  const post = (url) => request(fetchFn, url, { method: "POST" });
  return {
    mode: "live",
    status: () => get("api/status"),
    report: (scope = "auto") => get(`api/report?scope=${enc(scope)}`),
    caseFor: (id, scope = "auto") => get(`api/emails/${enc(id)}?scope=${enc(scope)}`),
    pageUrl: (id, role, page) => `api/emails/${enc(id)}/documents/${enc(role)}/pages/${page}.png`,
    retry: (id, scope = "auto") => post(`api/emails/${enc(id)}/retry?scope=${enc(scope)}`),
    run: ({ limit = null, resume = false } = {}) =>
      post(`run?resume=${resume}${limit ? `&limit=${limit}` : ""}`),
    dbStatus: () => get("api/db/status"),
    dbDocs: (name, { emailId = "", limit = 25, skip = 0 } = {}) =>
      get(`api/db/collections/${enc(name)}?limit=${limit}&skip=${skip}${emailId ? `&email_id=${enc(emailId)}` : ""}`),
  };
}

function staticApi(fetchFn) {
  let loaded = null;
  const load = () => (loaded ??= request(fetchFn, "report.json"));
  const readOnly = () => Promise.reject(new ApiError(0, "This is a read-only demo. Start the app to do this."));
  return {
    mode: "static",
    status: async () => {
      const data = await load();
      return { version: data.version ?? null, running: false, storage: "static", generated_at: data.generated_at };
    },
    report: () => load(),
    caseFor: async (id) => {
      const data = await load();
      const found = data.cases?.[id];
      if (!found) throw new ApiError(404, `No result for ${id}.`);
      return found;
    },
    pageUrl: () => null,
    retry: readOnly,
    run: readOnly,
    dbStatus: async () => ({ backend: "static", configured: false, connected: false, collections: [], error: null }),
    dbDocs: readOnly,
  };
}

/** Use the live API if it answers, otherwise fall back to the static report. */
export async function createApi(fetchFn = globalThis.fetch.bind(globalThis)) {
  try {
    const response = await fetchFn("api/status", { signal: AbortSignal.timeout(2500) });
    if (response.ok) return liveApi(fetchFn);
  } catch { /* no server: use the static report */ }
  return staticApi(fetchFn);
}
