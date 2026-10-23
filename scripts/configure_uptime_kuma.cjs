// Pin-specific local provisioning through Uptime Kuma's own Socket.IO API.
const path = require('node:path');
const { createRequire } = require('node:module');
const appRoot = path.resolve(process.argv[2]);
const localRequire = createRequire(path.join(appRoot, 'package.json'));
const { io } = localRequire('socket.io-client');
const socket = io('http://127.0.0.1:3001', { transports: ['websocket'], reconnection: false, timeout: 10000 });
const ready = new Promise((resolve, reject) => {
  const timeout = setTimeout(() => reject(new Error('Uptime Kuma did not send its initialization info.')), 15000);
  socket.once('info', () => { clearTimeout(timeout); resolve(); });
  socket.once('connect_error', error => { clearTimeout(timeout); reject(error); });
});
let monitors = {};
socket.on('monitorList', value => { monitors = value; });
const call = (event, ...args) => new Promise((resolve, reject) => socket.timeout(15000).emit(event, ...args, (error, result) => {
  if (error || result?.ok === false) reject(new Error(error?.message || result.msg || event + ' failed'));
  else resolve(result);
}));

(async () => {
  await ready;
  const username = process.argv[3], password = process.env.ACADEMY_KUMA_SETUP_PASSWORD;
  if (!password) throw new Error('No local credential supplied.');
  if (await call('needSetup')) await call('setup', username, password);
  await call('login', { username, password, token: '' });
  await call('getMonitorList');
  const targets = [
    { name: '학원 운영 서버', url: 'http://127.0.0.1:8003/api/ping' },
    { name: '공개 학생앱', url: 'https://app.5a-math.com/app' },
  ];
  const ids = [];
  for (const target of targets) {
    const existing = Object.values(monitors).find(monitor => monitor.name === target.name && monitor.url === target.url);
    if (existing) { ids.push(existing.id); continue; }
    const created = await call('add', { ...target, type: 'http', method: 'GET', interval: 60, retryInterval: 60,
      maxretries: 2, timeout: 15, maxredirects: 5, active: true, accepted_statuscodes: ['200-299'],
      notificationIDList: {}, upsideDown: false, ignoreTls: false, expiryNotification: false,
      conditions: [], kafkaProducerBrokers: [], kafkaProducerSaslOptions: {}, rabbitmqNodes: [] });
    ids.push(created.monitorID);
  }
  const existingPage = await fetch('http://127.0.0.1:3001/api/status-page/academy');
  if (existingPage.ok) {
    const page = await existingPage.json();
    const included = new Set((page.publicGroupList || []).flatMap(group => group.monitorList || []).map(monitor => String(monitor.id)));
    if (ids.some(id => !included.has(String(id)))) throw new Error('Existing academy page does not contain both monitors. Review it in Uptime Kuma; it was not overwritten.');
    console.log('Existing academy status page preserved. Monitors verified:', ids.length);
  } else {
    if (existingPage.status !== 404) throw new Error('Cannot inspect existing status page: ' + existingPage.status);
    await call('addStatusPage', '학원 서버 상태', 'academy');
    await call('saveStatusPage', 'academy', { slug: 'academy', title: '학원 서버 상태', description: '운영 서버와 공개 학생앱 · 외부 알림 없음',
      theme: 'auto', autoRefreshInterval: 60, showTags: false, footerText: '서버 PC 내부 감시', customCSS: '', showPoweredBy: true,
      rssTitle: '', showOnlyLastHeartbeat: false, showCertificateExpiry: false, analyticsType: null, analyticsId: '', analyticsScriptUrl: '', domainNameList: [] },
    '', [{ name: '학원 서비스', monitorList: ids.map(id => ({ id, sendUrl: false })) }]);
    console.log('Created local status page. Monitors:', ids.length);
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(() => socket.close());
