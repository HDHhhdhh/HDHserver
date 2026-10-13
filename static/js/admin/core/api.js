import { ensureOk, fetchJson, fetchJsonChecked, fetchJsonOr, sendJson } from '../../shared/api.js';

export const api = {
  get: (url, init) => fetchJson(url, init),
  getStrict: (url, label, init) => fetchJsonChecked(url, label, init),
  getOr: (url, fallback, init) => fetchJsonOr(url, fallback, init),
  post: (url, data, init) => sendJson(url, data, init),
  postStrict: async (url, data, label = url, init) => {
    const response = await sendJson(url, data, init);
    await ensureOk(response, label);
    return response.json();
  },
};
