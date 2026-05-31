import { fetchJson, fetchJsonOr, sendJson } from '../../shared/api.js';

export const api = {
  get: (url, init) => fetchJson(url, init),
  getOr: (url, fallback, init) => fetchJsonOr(url, fallback, init),
  post: (url, data, init) => sendJson(url, data, init),
};
