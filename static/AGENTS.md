# STATIC KNOWLEDGE BASE

## Overview
Static HTML/CSS assets define the browser surfaces. Flask serves these files directly through `routes/pages.py`.

## Structure
```
static/
|-- admin.html          # admin shell
|-- student.html        # student shell for /student/<sid>; the /student-test alias is retired
|-- all.html            # all-students shell
|-- tests.html          # test management shell
|-- css/                # shared and page-specific styles
`-- js/                 # page entrypoints, shared/admin/all modules, answer map
```

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Admin shell | `admin.html` | Loads `js/admin/main.js`. Keep required DOM ids stable. |
| Student shell | `student.html` | Loads `js/student/bootstrapState.js`, `js/student/watchState.js`, `js/student/playback.js`, `js/student/reviewPlaylist.js`, `js/student/announcementState.js`, then `js/student/testPresentation.js` before `js/student.js`; `#vidList` and the immediately following `#previousVideos` share the one `#player` surface. |
| Student OCR capture | `student-test-capture.html`, `js/student-test-capture.js`, `css/student-test-ocr.css` | Camera-only, token-launched, default-off 20-question capture/review flow. |
| All-students shell | `all.html` | Loads `js/all/main.js`. |
| Test management shell | `tests.html` | Loads `css/tests.css` after the shared cascade and module entry `js/tests.js`, which imports the DOM/transport-free catalog, editor, and statistics state modules under `js/tests/`. |
| Video/calendar/files | `video-manage.html`, `school-cal.html`, `file-manage.html` | Standalone management shells and page scripts. |
| Admin styling | `css/admin.css` | Large shared admin stylesheet; cascade changes can affect many panels. |
| Student styling | `css/student.css` | Student-page layout and announcement/test card styling. |

## Conventions
- Treat HTML shells as DOM contracts for their JS modules.
- `routes/pages.py` serves these files directly; there is no template-rendering layer to repair missing hooks.
- Admin/all/tests/video/school-calendar shells load `js/admin/demo/bootstrap.js` before their normal entrypoint. Preserve that ordering.
- The test shell loads only the module entrypoint; keep catalog/list state in `js/tests/catalogState.js`, answer/CSV projections in `js/tests/catalogEditorState.js`, statistics/search/detail projection in `js/tests/catalogStatisticsState.js`, page-scoped cascade in `css/tests.css`, and page DOM/fetch/file/modal orchestration in `js/tests.js` rather than adding more shell script or inline-style blocks.
- The student shell loads deferred classic scripts in the fixed order `js/student/bootstrapState.js` → `js/student/watchState.js` → `js/student/playback.js` → `js/student/reviewPlaylist.js` → `js/student/announcementState.js` → `js/student/testPresentation.js` → `js/student.js`, so all injected bootstrap, watch, playback, local-review, announcement-state, and test-presentation contracts exist before the page entrypoint runs.
- Keep Korean UI text readable as UTF-8.
- Do not remove ids/classes that feature modules query unless you update every caller.
- Preserve the student review DOM contract: `#previousVideosToggle` controls `#previousVideosPanel`, `#previousVideosRegister` is a separate action, and `#previousVidList` introduces neither a second player nor a modal.
- Prefer scoped CSS changes. `admin.css` is broad and selector collisions are easy.
- Follow `css/AGENTS.md` for stylesheet-specific cascade, modal, responsive, and font rules.
- Generated screenshots and QA artifacts belong under `generated/`, not `static/`, unless the app serves them intentionally.

## Anti-Patterns
- Do not turn static shells into Flask template dependencies without a route migration.
- Do not inline large behavior blocks when an existing JS module owns that feature.
- Do not edit generated answer-link maps by hand; regenerate them from the scripts when possible.
- Do not delete unreferenced/copy assets solely from import-graph evidence; root static serving means external bookmarks can still reach them.
