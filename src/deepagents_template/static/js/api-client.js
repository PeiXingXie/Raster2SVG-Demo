function parseJsonResponseText(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function parseJsonResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      const message = typeof detail === "string"
        ? detail
        : (detail?.message || data.message || "Request failed");
      const error = new Error(message);
      error.responseData = typeof detail === "object" && detail ? detail : data;
      throw error;
    }
    return data;
  }

  const text = await response.text();
  if (!response.ok) {
    throw new Error(text || `Request failed (${response.status})`);
  }
  const data = parseJsonResponseText(text);
  if (!data) {
    throw new Error(text || "Server returned a non-JSON response");
  }
  return data;
}

export async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  return parseJsonResponse(response);
}
