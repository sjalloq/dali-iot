// One thin fetch wrapper. Every error becomes an Error with the server's detail.
async function call(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try {
    data = await r.json();
  } catch {
    /* no body */
  }
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : JSON.stringify(d || r.statusText));
  }
  return data;
}

export const api = {
  get: (p) => call("GET", p),
  post: (p, b) => call("POST", p, b ?? {}),
  put: (p, b) => call("PUT", p, b),
  del: (p) => call("DELETE", p),
};

export function useToastErrors(toast) {
  return async (fn, okMessage) => {
    try {
      const out = await fn();
      if (okMessage) toast.add({ severity: "success", summary: okMessage, life: 1500 });
      return out;
    } catch (e) {
      toast.add({ severity: "error", summary: "Failed", detail: e.message, life: 6000 });
      return undefined;
    }
  };
}
