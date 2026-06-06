# CORE KNOWLEDGE BASE

## Overview
Shared backend helpers live here. Keep pure merge rules, persistence wrappers, chatbot knowledge, path constants, network gating, and storage locks distinct.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Log merge/conflict rules | `log_rules.py` | Pure functions only. No Flask, SQLite, JSON file reads, or runtime-data repair. |
| Progress/watch merge rules | `progress_rules.py` | Manual white/skip/none states stay authoritative over automatic watch updates. |
| Log persistence | `log_repository.py` | SQLite plus `logs.json` dual-read/dual-write contract. |
| Runtime paths | `paths.py` | Canonical JSON/SQLite path constants. |
| JSON storage/locks | `storage.py` | Use `save_atomic` and file locks for operational JSON writes. |
| Admin chatbot knowledge | `admin_chat.py` | Update when user-facing features, data contracts, or safety rules change. |
| Network gating | `network_access.py` | Answer-link and academy-network visibility behavior. |
| Ghost student guards | `ghost_student.py` | Blocks writes for synthetic/placeholder students. |

## Conventions
- Keep `log_rules.py` and `progress_rules.py` deterministic and side-effect free.
- Route handlers should call core helpers instead of duplicating merge/storage rules.
- Preserve unknown keys in log/progress records unless a route explicitly clears them.
- Keep Korean text as UTF-8. Do not replace unreadable legacy text with `????`.
- Importing `core` modules should not start Flask, touch runtime JSON, or initialize SQLite schema unless that is the module's explicit job.

## Anti-Patterns
- Do not move homework placeholder repair into `log_rules.py`; it can depend on student/book runtime data.
- Do not collapse watch/progress auto-status rules into log rules.
- Do not bypass `LogRepository` for class-log writes.
- Do not add broad data cleanup inside pure helpers.
