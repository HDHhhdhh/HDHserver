import { fetchJson } from '../../shared/api.js';

export function paymentMessage(error) {
  try { return JSON.parse(error.body).message || error.message; } catch { return error.message || '연결을 확인해 주세요.'; }
}

export function operationUuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let i=0; i<bytes.length; i++) bytes[i] = Math.floor(Math.random()*256);
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

export class PaymentClient {
  constructor({ request = fetchJson, uuid = operationUuid } = {}) {
    this.request = request;
    this.uuid = uuid;
    this.pending = null;
    this.saving = false;
    this.readSequence = 0;
  }
  async readAccount(sid) {
    const sequence = ++this.readSequence;
    try {
      const data = await this.request(`/api/payments/account?${new URLSearchParams({ sid })}`, { cache: 'no-store' });
      return sequence === this.readSequence ? data : null;
    } catch (error) {
      if (sequence !== this.readSequence) return null;
      throw error;
    }
  }
  invalidateReads() { this.readSequence += 1; }
  async save(sid, revision, command) {
    if (this.saving) throw new Error('이미 저장하고 있습니다.');
    if (!this.pending) {
      this.pending = JSON.parse(JSON.stringify({ ...command, sid, baseRevision: revision, operationId: this.uuid() }));
    } else if (this.pending.sid !== sid) {
      throw new Error('이전 학생의 저장 결과를 먼저 확인해 주세요.');
    }
    this.saving = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const result = await this.request('/api/payments/command', { method: 'POST', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this.pending), signal: controller.signal });
      if (!result?.ok || !Number.isInteger(result.revision)) throw new Error('저장 응답을 확인하지 못했습니다. 같은 작업으로 재시도해 주세요.');
      this.pending = null;
      return result;
    } catch (error) {
      // A transport/5xx failure can follow a committed transaction. Keep its exact operation.
      if ([400, 401, 403, 404, 409, 413].includes(error.status)) this.pending = null;
      throw error;
    } finally {
      clearTimeout(timeout);
      this.saving = false;
    }
  }
}
