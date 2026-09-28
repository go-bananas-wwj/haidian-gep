# Agent Research 80/20 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace blanket manual intervention with official-source research, truthful AEF readiness, risk-tiered candidates, A1 evidence drawers, and auditable batch confirmation.

**Architecture:** A deterministic research layer searches local evidence and a versioned official-source registry, verifies online sources, inspects AEF assets, and returns A/B/research-gap/C outcomes. DeepSeek explains tool results but cannot choose values or trust levels; the task service persists risk, evidence, batch reviews, and events before the browser renders them.

**Tech Stack:** Python 3.11 standard library, SQLite, urllib, vanilla JS/CSS/SVG, Docker Compose, DeepSeek JSON API.

**Spec:** `docs/superpowers/specs/2026-09-28-agent-research-80-20-design.md`

## Global Constraints

- Never fabricate an 80% completion ratio or AEF land-cover result.
- A auto-adoption requires an official/local exact fact or fully validated deterministic/AEF result.
- B candidates may be used only after individual or batch review.
- Research gaps remain formal blockers but are not labeled manual intervention.
- C is reserved for permission, conflict, method-boundary, or expert decisions.
- Batch confirmation can approve only current-version A/B nodes; it never bypasses research gaps, C, failures, or version conflicts.
- DeepSeek keys remain worker-only and never enter persisted evidence, events, Web assets, or exports.
- Existing tasks with legacy `manual_required/source_missing` are rescheduled under `research-v2`.
- No new production dependency is required for this phase; AEF execution reports missing prerequisites truthfully.

## Review Focus

- An official URL is unavailable or redirects outside the allowed government domain: do not auto-adopt it (Task 1).
- A source fact is official but only a proxy for the method field: classify B, never A (Task 2).
- AEF VRT exists but labels/boundary/runtime are missing: return research-gap, never a green-area number (Task 3).
- A batch confirmation races with a newer node version: reject the whole stale batch without partial approval (Task 4).
- A restored legacy task contains source-missing manual states: reschedule only those states, preserving genuine C decisions (Task 2).

---

### Task 1: Official Source Registry and Online Verification

**Files:**
- Create: `gep/official_sources.py`
- Create: `gep/official_sources.json`
- Test: `tests/test_official_sources.py`

**Interfaces:**
- Produces: `OfficialSourceRegistry(path: Path | None = None)`
- Produces: `search(work_order: dict[str, Any]) -> list[dict[str, Any]]`
- Produces: `verify(record: dict[str, Any]) -> dict[str, Any]`

- [ ] Write failing tests for exact node matching, official-domain allowlist, redirect rejection, online verification metadata, and the known 2024 green/water records.
- [ ] Run `python -m unittest tests.test_official_sources -v`; expect failure because the registry does not exist.
- [ ] Implement the JSON registry and dependency-free verifier; record status, checked time, final URL, response metadata, and sanitized failures without downloading full PDFs during every job.
- [ ] Run focused and full tests; expect green.
- [ ] Commit with `feat: add official GEP source research`.

### Task 2: Research Outcomes, Risk Policy, and Legacy Migration

**Files:**
- Create: `gep/research.py`
- Modify: `gep/evidence_catalog.py`
- Modify: `gep/supplement.py`
- Modify: `gep/task_service.py`
- Modify: `tests/test_evidence_catalog.py`
- Modify: `tests/test_task_service.py`
- Test: `tests/test_research.py`

**Interfaces:**
- Produces: `ResearchWorkflow(provider, local_catalog, official_registry, aef_tool).run(work_order) -> dict`
- Produces: outcomes `candidate` with `risk_tier=A|B`, `research_complete`, and `manual_required` with C reason codes.
- Produces: `enqueue_all_supplements(..., scheduler_version="research-v2")` legacy rescheduling behavior.

- [ ] Write failing tests for A exact facts, B proxies/conflicts, research-gap, genuine C decisions, official-source citation validation, and legacy source-missing rescheduling.
- [ ] Run focused tests; expect unsupported outcome/risk failures.
- [ ] Implement risk policy and workflow composition; no evidence after all tools becomes `research_complete`, not C.
- [ ] Persist `auto_verified`, `review_recommended`, `research_complete`, risk metadata, tool log, and new events with optimistic version checks.
- [ ] Run focused and full tests; expect green.
- [ ] Commit with `feat: classify agent research by evidence risk`.

### Task 3: Truthful AEF Spatial Asset Tool

**Files:**
- Create: `gep/geo/aef_tool.py`
- Modify: `gep/research.py`
- Test: `tests/test_aef_tool.py`

**Interfaces:**
- Produces: `AefSpatialTool(data_root).inspect(work_order) -> dict[str, Any]`
- Returns `ready`, `research_gap`, or `not_applicable`, with VRT metadata and exact prerequisites.

- [ ] Write failing tests for 2024 VRT parsing, 64 bands, 10 m resolution, UTM 50N, safe remote COG URI, missing boundary/labels/runtime, and rejection of a fabricated classification claim.
- [ ] Run `python -m unittest tests.test_aef_tool -v`; expect missing module.
- [ ] Implement XML-only asset inspection and evidence hashing; do not classify without boundary, labels, runtime, and validation assets.
- [ ] Connect AEF inspection logs to applicable green/ecosystem-area work orders.
- [ ] Run focused and full tests; expect green.
- [ ] Commit with `feat: inspect AEF spatial research assets`.

### Task 4: Batch Review Domain and API

**Files:**
- Modify: `gep/task_service.py`
- Modify: `gep/api.py`
- Modify: `gep/web/api.js`
- Modify: `tests/test_task_service.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: `batch_review_preview(task_id) -> dict`
- Produces: `create_batch_review(task_id, expected_graph_version, ignore_individual_review, reviewer, note) -> dict`
- Produces: GET preview and POST batch-review endpoints.

- [ ] Write failing tests for preview counts, cancel/no mutation, A/B bulk approval, hard-blocker exclusion, trusted reviewer identity, idempotent audit rows, and all-or-nothing stale-version rejection.
- [ ] Run focused tests; expect missing methods/routes.
- [ ] Add `batch_reviews` and `batch_review_nodes` migrations and implement transactional preview/confirm.
- [ ] Add authenticated API routes and Web client methods.
- [ ] Run focused and full tests; expect green.
- [ ] Commit with `feat: add auditable batch review`.

### Task 5: A1 Evidence Drawer and 80/20 Task UI

**Files:**
- Modify: `gep/web/index.html`
- Modify: `gep/web/app.js`
- Modify: `gep/web/graph.js`
- Modify: `gep/web/styles.css`
- Modify: `tests/web/test_task_canvas.py`
- Modify: `tests/test_deploy_config.py`

**Interfaces:**
- Consumes: risk/status fields and batch APIs from Tasks 2–4.
- Produces: A1 drawer, status-driven actions, batch preview dialog, and A/B/gap/C summary.

- [ ] Write failing contracts for removal of “智能体如何补充”, A1 source-first order, collapsed execution log, automatic-adoption copy, risk-specific buttons, five-way summary, and batch modal confirm/cancel.
- [ ] Run Web tests; expect failure on old drawer/status copy.
- [ ] Implement A1 drawer and state labels; A nodes show only mark-problem/correct, B shows one confirm action, gap shows automatic search coverage, C shows reason-specific intervention.
- [ ] Implement batch preview modal; confirm posts a batch review, cancel opens the per-node queue.
- [ ] Verify desktop, 390 px mobile, keyboard/focus, event flow, refresh, and old-task rescheduling in Playwright.
- [ ] Run full tests; expect green.
- [ ] Commit with `feat: deliver evidence-first 80-20 review UI`.

### Task 6: Documentation, Live Verification, Deployment, and GitHub Sync

**Files:**
- Modify: `deploy/README.md`
- Modify: `/home/wwj/GEP/overleaf/implementation/main.tex`
- Modify tests only if verification exposes a defect.

**Interfaces:**
- Consumes all prior tasks.
- Produces deployed release, backups, sanitized browser evidence, updated Overleaf commit, merged `main`, and pushed GitHub `main`.

- [ ] Update deployment and Overleaf wording for official research, AEF readiness, A1 drawer, risk tiers, and batch confirmation.
- [ ] Run the complete local suite and secret scan.
- [ ] Run a real official-source verification and DeepSeek smoke test without recording prompts, raw responses, or keys.
- [ ] Run browser acceptance on a fresh and a legacy task; record honest A/B/gap/C counts and batch behavior.
- [ ] Back up host runtime, deploy a new immutable release, and verify 9088, worker-only key, task persistence, source tool results, AEF readiness, batch review, and no secret leakage.
- [ ] Run the complete host suite in a clean environment.
- [ ] Commit docs in both repositories, merge the feature branch to local `main`, push `main` and the Overleaf repository to their configured GitHub remotes, and report exact commits/URLs.
