export const CT = { 'Content-Type': 'application/json' };

export const getJSON = (url) =>
  fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(r => r.json());

export const postJSON = async (url, data) => {
  const res = await fetch(url, {
    method: 'POST',
    headers: CT,
    credentials: 'same-origin',
    cache: 'no-store',
    body: JSON.stringify(data),
  });
  return res; // ✅ Response 그대로 리턴
};

export const patchField = async (id, field, value) => {
  const res = await postJSON('/api/update', { id, field, value });

  // ✅ 여기서 성공/실패를 확실히 갈라준다
  if (!res.ok) {
    let txt = '';
    try { txt = await res.text(); } catch {}
    throw new Error(`PATCH failed ${res.status}: ${txt}`);
  }

  // 서버가 "OK" 문자열을 주든 JSON을 주든 상관없이
  // 일단 성공이면 res를 그대로 반환
  return res;
};
