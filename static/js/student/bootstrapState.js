(function studentBootstrapStateModule(global) {
  'use strict';

  function requireFunction(value, name) {
    if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    return value;
  }

  function projectBootstrapInitialData(bootstrap, watchRaw, options = {}) {
    const resolveAcademyAccess = requireFunction(
      options.resolveAcademyAccess,
      'resolveAcademyAccess',
    );
    const academyAllowed = resolveAcademyAccess(options.publicMode === true, bootstrap);

    return [
      Array.isArray(bootstrap.students)
        ? bootstrap.students
        : (bootstrap.student ? [bootstrap.student] : []),
      Array.isArray(bootstrap.videos) ? bootstrap.videos : [],
      bootstrap.updates || {},
      bootstrap.materials || {},
      bootstrap.assigns || {},
      bootstrap.absent || {},
      bootstrap.logs || {},
      watchRaw,
      {
        courseBlocked: bootstrap.courseBlocked === true,
        selfStudy: bootstrap.selfStudy === true,
        blockMessage: bootstrap.blockMessage || '',
        courseVideosCompleted: bootstrap.courseVideosCompleted === true,
        academyAccessAllowed: academyAllowed,
        academyOnlyMessage: bootstrap.academyOnlyMessage
          || bootstrap.academyOnlyNotice
          || bootstrap.restrictedMessage
          || '',
        assignedTests: Array.isArray(bootstrap.assignedTests) ? bootstrap.assignedTests : [],
        homeworkBooks: Array.isArray(bootstrap.homeworkBooks) ? bootstrap.homeworkBooks : [],
        reviewVideos: bootstrap.reviewVideos,
        reviewVideosMalformed: !Array.isArray(bootstrap.reviewVideos),
        ghostStudent: bootstrap.ghostStudent === true,
        redirectSid: bootstrap.redirectSid || bootstrap.recoveredSid || '',
        recoveryReason: bootstrap.recoveryReason || '',
        dashboard: bootstrap.dashboard && typeof bootstrap.dashboard === 'object'
          ? bootstrap.dashboard
          : null,
        videoProjectionAuthoritative: true,
      },
    ];
  }

  async function loadInitialData(options = {}) {
    const publicMode = options.publicMode === true;
    const date = options.date;
    const resolveAcademyAccess = requireFunction(
      options.resolveAcademyAccess,
      'resolveAcademyAccess',
    );

    if (publicMode) {
      const loadPublicBootstrap = requireFunction(
        options.loadPublicBootstrap,
        'loadPublicBootstrap',
      );
      const loaded = await loadPublicBootstrap({
        adapter: options.publicSession,
        pageSid: options.pageSid,
        date,
      });
      return {
        activeSid: loaded.activeSid,
        initialData: projectBootstrapInitialData(loaded.bootstrap, loaded.watch, {
          publicMode,
          resolveAcademyAccess,
        }),
      };
    }

    const fetchImpl = requireFunction(options.fetchImpl, 'fetchImpl');
    const watchRequest = fetchImpl(`/api/watch/latest?sid=${encodeURIComponent(options.sid)}`)
      .then(response => response.json())
      .catch(() => ({}));

    const query = new URLSearchParams({
      sid: String(options.sid),
      date,
    }).toString();
    const response = await fetchImpl(`/api/student/bootstrap?${query}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`bootstrap ${response.status}`);
    const bootstrap = await response.json();
    return {
      activeSid: '',
      initialData: projectBootstrapInitialData(bootstrap, await watchRequest, {
        publicMode,
        resolveAcademyAccess,
      }),
    };
  }

  global.StudentBootstrapState = Object.freeze({
    loadInitialData,
    projectBootstrapInitialData,
  });
})(window);
