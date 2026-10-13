// Pure catalog parsing. Playback URLs are issued only by the academy-gated server.
export const GICHUL_COURSE = '기출엄선';
export const GICHUL_OVERLAY_FIELD = 'gichulSelectionEnabled';
const hosts = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com']);

export function isYouTubeMid(mid) {
  return /^(?:ytv_[A-Za-z0-9_-]{11}|ytp_[A-Za-z0-9_-]{10,100})(?:_r[0-9]{1,12})?$/.test(String(mid || ''));
}

export function parseYouTubeUrl(raw, catalogId = null) {
  let u;
  try { u = new URL(String(raw || '').trim()); } catch { return null; }
  if (!hosts.has(u.hostname.toLowerCase())) return null;
  if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password || (u.port && !['80', '443'].includes(u.port))) throw new Error('유효한 YouTube https 링크를 입력하세요.');
  for (const key of ['v', 'list', 'start', 't']) if (u.searchParams.getAll(key).length > 1) throw new Error('YouTube 링크에 중복 식별자가 있습니다.');
  const path = u.pathname.replace(/\/$/, '');
  const parts = path.replace(/^\//, '').split('/');
  let kind = 'video';
  let id = '';
  if (['youtu.be', 'www.youtu.be'].includes(u.hostname) && parts.length === 1) id = parts[0];
  else if (path === '/watch') id = u.searchParams.get('v') || '';
  else if (parts.length === 2 && ['embed', 'shorts', 'v'].includes(parts[0])) {
    id = parts[1];
    if (parts[0] === 'embed' && id === 'videoseries') { kind = 'playlist'; id = u.searchParams.get('list') || ''; }
  } else if (['/playlist', '/embed'].includes(path)) { kind = 'playlist'; id = u.searchParams.get('list') || ''; }
  else throw new Error('영상 또는 재생목록 링크만 지원합니다. 실시간 방송 링크는 제외됩니다.');
  if (!(kind === 'video' ? /^[A-Za-z0-9_-]{11}$/ : /^[A-Za-z0-9_-]{10,100}$/).test(id)) throw new Error('YouTube 영상/재생목록 식별자가 올바르지 않습니다.');
  const rawTime = (u.searchParams.get('start') || u.searchParams.get('t') || (u.hash.startsWith('#t=') ? u.hash.slice(3) : '')).toLowerCase();
  let start = 0;
  if (/^\d+$/.test(rawTime)) start = Number(rawTime);
  else if (rawTime) {
    const time = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(rawTime);
    if (!time) throw new Error('YouTube 시작 시간 형식이 올바르지 않습니다.');
    start = Number(time[1] || 0) * 3600 + Number(time[2] || 0) * 60 + Number(time[3] || 0);
  }
  if (start > 604800) throw new Error('YouTube 시작 시간이 너무 큽니다.');
  const query = new URLSearchParams({ [kind === 'video' ? 'v' : 'list']: id });
  if (start) query.set('t', String(start));
  if (catalogId != null && !/^[1-9][0-9]{0,11}$/.test(String(catalogId))) throw new Error('YouTube 영상에는 유효한 카탈로그 ID가 필요합니다.');
  return { provider: 'youtube', youtubeKind: kind, youtubeId: id, youtubeStart: start,
    mid: (kind === 'video' ? 'ytv_' : 'ytp_') + id + (catalogId == null ? '' : `_r${catalogId}`),
    url: `https://www.youtube.com/${kind === 'video' ? 'watch' : 'playlist'}?${query}` };
}

export function automaticVideoCourse(student) {
  return student?.gichulSelectionEnabled === true ? GICHUL_COURSE : String(student?.subCurriculum || '').trim();
}

export function videoInAssignmentScope(student, video) {
  const subject = String(student?.curriculum || '').trim().toLowerCase();
  const base = String(student?.subCurriculum || '').trim().toLowerCase();
  const course = String(video?.subCurriculum || '').trim().toLowerCase();
  return !!subject && subject === String(video?.curriculum || '').trim().toLowerCase()
    && (!base || course === base || course === GICHUL_COURSE);
}
