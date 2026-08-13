import { JSON_HEADERS, ensureOk, fetchJson, fetchJsonOr, sendJson } from '../../shared/api.js';

export const CT = JSON_HEADERS;

const SAME_ORIGIN_NO_STORE = { credentials: 'same-origin', cache: 'no-store' };

export const getJSON = (url) => fetchJson(url, SAME_ORIGIN_NO_STORE);

export const getJSONOr = (url, fallback) => fetchJsonOr(url, fallback, SAME_ORIGIN_NO_STORE);

export const postJSON = async (url, data) => {
  return await sendJson(url, data, {
    credentials: 'same-origin',
    cache: 'no-store',
  });
};

export const patchField = async (id, field, value) => {
  const res = await postJSON('/api/update', { id, field, value });

  await ensureOk(res, 'PATCH');

  return res;
};
