import assert from 'node:assert/strict';
import { PaymentClient, operationUuid } from '../static/js/admin/features/paymentClient.js';

const originalCrypto = Object.getOwnPropertyDescriptor(globalThis,'crypto');
Object.defineProperty(globalThis,'crypto',{ configurable:true,value:{ getRandomValues:(bytes) => bytes.fill(17) } });
assert.match(operationUuid(),/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
if (originalCrypto) Object.defineProperty(globalThis,'crypto',originalCrypto);
else delete globalThis.crypto;

let calls = [], fail = true;
const client = new PaymentClient({ uuid:() => 'operation-one', request:async (_url, options) => {
  calls.push(JSON.parse(options.body));
  if (fail) throw new Error('response lost after commit');
  return { ok:true, revision:3 };
} });
await assert.rejects(client.save('student-a',2,{ action:'payment',amount:450000 }));
assert.equal(client.pending.operationId,'operation-one');
await assert.rejects(client.save('student-b',0,{ action:'payment',amount:1 }));
fail = false;
await client.save('student-a',999,{ action:'payment',amount:1 });
assert.deepEqual(calls[0],calls[1]);
assert.equal(client.pending,null);

let resolve;
const concurrent = new PaymentClient({ uuid:() => 'concurrent', request:() => new Promise((r) => { resolve=r; }) });
const pending = concurrent.save('a',0,{ action:'configure' });
await assert.rejects(concurrent.save('a',0,{ action:'configure' }));
resolve({ ok:true,revision:1 });
await pending;

const errors = new PaymentClient({ uuid:() => 'conflict',request:async() => { throw Object.assign(new Error('conflict'),{ status:409 }); } });
await assert.rejects(errors.save('a',0,{ action:'configure' }));
assert.equal(errors.pending,null);

const readers = [];
const latest = new PaymentClient({ request:() => new Promise((resolve) => readers.push(resolve)) });
const old = latest.readAccount('old'), fresh = latest.readAccount('new');
readers[1]({ student:'new' }); readers[0]({ student:'old' });
assert.deepEqual(await fresh,{ student:'new' });
assert.equal(await old,null);
console.log('Payment client: exact retry, double-submit, conflict and stale-read checks passed.');
