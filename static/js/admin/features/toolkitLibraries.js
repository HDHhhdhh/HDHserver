const jobs = new Map();
const libraries = {
  tomSelect: { global: 'TomSelect', base: '/vendor/tom-select/2.6.2/', js: 'tom-select.complete.min.js', css: 'tom-select.default.min.css' },
  tabulator: { global: 'Tabulator', base: '/vendor/tabulator-tables/6.7.1/', js: 'tabulator.min.js', css: 'tabulator.min.css' },
  echarts: { global: 'echarts', base: '/vendor/echarts/6.1.0/', js: 'echarts.min.js' },
};

export function loadToolkitLibrary(name) {
  const spec = libraries[name];
  if (!spec) return Promise.reject(new Error('알 수 없는 화면 도구입니다.'));
  if (jobs.has(name)) return jobs.get(name);
  const job = (async () => {
    if (spec.css && !document.querySelector(`link[data-toolkit="${name}"]`)) {
      const link = document.createElement('link');
      link.rel = 'stylesheet'; link.href = spec.base + spec.css; link.dataset.toolkit = name;
      await new Promise((resolve, reject) => {
        link.onload = resolve;
        link.onerror = () => { link.remove(); reject(new Error('화면 스타일을 불러오지 못했습니다.')); };
        document.head.append(link);
      });
    }
    if (!globalThis[spec.global]) {
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = spec.base + spec.js;
        script.onload = resolve;
        script.onerror = () => { script.remove(); reject(new Error('화면 도구를 불러오지 못했습니다.')); };
        document.head.append(script);
      });
    }
    if (!globalThis[spec.global]) throw new Error('화면 도구 초기화에 실패했습니다.');
    return globalThis[spec.global];
  })();
  jobs.set(name, job);
  job.catch(() => { if (jobs.get(name) === job) jobs.delete(name); });
  return job;
}
