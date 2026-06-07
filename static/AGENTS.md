# STATIC KNOWLEDGE BASE

## Overview
Static HTML/CSS assets define the browser surfaces. Flask serves these files directly through `routes/pages.py`.

## Structure
```
static/
|-- admin.html          # admin shell
|-- student.html        # student shell for /student/<sid> and /student-test/<sid>
|-- all.html            # all-students shell
|-- tests.html          # test management shell
|-- css/                # shared and page-specific styles
`-- js/                 # frontend modules and generated answer-link maps
```

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Admin shell | `admin.html` | Loads `js/admin/main.js`. Keep required DOM ids stable. |
| Student shell | `student.html` | Loads `js/student.js`; used by multiple student routes. |
| All-students shell | `all.html` | Loads `js/all/main.js`. |
| Test management shell | `tests.html` | Loads `js/tests.js`. |
| Admin styling | `css/admin.css` | Large shared admin stylesheet; cascade changes can affect many panels. |
| Student styling | `css/student.css` | Student-page layout and announcement/test card styling. |

## Conventions
- Treat HTML shells as DOM contracts for their JS modules.
- Keep Korean UI text readable as UTF-8.
- Do not remove ids/classes that feature modules query unless you update every caller.
- Prefer scoped CSS changes. `admin.css` is broad and selector collisions are easy.
- Follow `css/AGENTS.md` for stylesheet-specific cascade, modal, responsive, and font rules.
- Generated screenshots and QA artifacts belong under `generated/`, not `static/`, unless the app serves them intentionally.

## Anti-Patterns
- Do not turn static shells into Flask template dependencies without a route migration.
- Do not inline large behavior blocks when an existing JS module owns that feature.
- Do not edit generated answer-link maps by hand; regenerate them from the scripts when possible.
