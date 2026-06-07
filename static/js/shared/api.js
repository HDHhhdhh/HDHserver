export const JSON_HEADERS = Object.freeze({ 'Content-Type': 'application/json' });

export class ApiError extends Error {
  constructor(message, { status = 0, body = '', response = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.response = response;
  }
}

function headerObject(headers) {
  if (!headers) return {};
  if (typeof Headers !== 'undefined' && headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) return Object.fromEntries(headers);
  return headers;
}

export async function readTextSafe(response) {
  try {
    return await response.text();
  } catch {
    return '';
  }
}

export async function ensureOk(response, label = 'request') {
  if (response.ok) return response;
  const body = await readTextSafe(response);
  throw new ApiError(`${label} failed ${response.status}: ${body}`, {
    status: response.status,
    body,
    response,
  });
}

export async function fetchJson(url, init = {}) {
  const response = await fetch(url, init);
  return await response.json();
}

export async function fetchJsonChecked(url, label = 'request', init = {}) {
  const response = await fetch(url, init);
  await ensureOk(response, label);
  return await response.json();
}

export async function fetchJsonOr(url, fallback, init = {}) {
  try {
    return await fetchJson(url, init);
  } catch {
    return fallback;
  }
}

export async function sendJson(url, data, init = {}) {
  const { headers, ...rest } = init;
  return await fetch(url, {
    method: 'POST',
    ...rest,
    headers: {
      ...JSON_HEADERS,
      ...headerObject(headers),
    },
    body: JSON.stringify(data),
  });
}
