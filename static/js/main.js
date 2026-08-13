/* global fetch */
const $ = (id) => document.getElementById(id);

const LS_TOKEN = "studentToken";

/* =========================
   Existing student page code
   ========================= */
function msg(text, type = "") {
  const el = $("msg");
  el.className = "msg " + (type || "");
  el.textContent = text || "";
}

async function api(path, body, token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch {}
  return { ok: res.ok, status: res.status, data };
}

async function requireLogin() {
  const token = localStorage.getItem(LS_TOKEN);
  if (!token) { location.href = "/"; return null; }

  const r = await api("/api/auth/me", null, token);
  if (!r.ok || !r.data?.ok) {
    localStorage.removeItem(LS_TOKEN);
    location.href = "/";
    return null;
  }

  $("sidText").textContent = r.data.sid;
  return token;
}

$("logoutBtn").addEventListener("click", () => {
  localStorage.removeItem(LS_TOKEN);
  location.href = "/";
});

(async () => {
  const token = await requireLogin();
  if (!token) return;

  $("pwBtn").addEventListener("click", async () => {
    const oldPassword = ($("oldPw").value || "").trim();
    const newPassword = ($("newPw").value || "").trim();
    if (!oldPassword || !newPassword) { msg("비번 입력해.", "err"); return; }

    const r = await api("/api/auth/change-password", { oldPassword, newPassword }, token);
    if (r.ok && r.data?.ok) msg("비밀번호 변경됨", "ok");
    else msg(r.data?.error === "bad old password" ? "현재 비번 틀림." : "변경 실패.", "err");
  });

  $("idBtn").addEventListener("click", async () => {
    const password = ($("idPw").value || "").trim();
    const newId = ($("newId").value || "").trim();
    if (!password || !newId) { msg("비번/새 아이디 입력해.", "err"); return; }

    const r = await api("/api/auth/change-id", { password, newId }, token);
    if (r.ok && r.data?.ok && r.data?.token) {
      localStorage.setItem(LS_TOKEN, r.data.token);
      $("sidText").textContent = r.data.sid;
      msg("아이디 변경됨", "ok");
    } else {
      const e = r.data?.error;
      msg(
        e === "bad newId format" ? "새 아이디 형식이 이상함." :
        e === "newId already exists" ? "이미 있는 아이디." :
        e === "bad password" ? "비번 틀림." :
        "아이디 변경 실패.",
        "err"
      );
    }
  });
})();
