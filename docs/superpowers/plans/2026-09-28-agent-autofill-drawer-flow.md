# Agent Autofill, Drawer, and Flow Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically resolve every pending GEP node to a reviewable candidate or an explicit human-intervention state, while showing real event flow on the canvas and all detail in a right-side drawer.

**Architecture:** Keep the existing SQLite job queue and single worker, add an environment-selected DeepSeek workflow behind the existing `SupplementWorkflow` boundary, and enrich each work order only with admitted local evidence. Persist every transition before the browser animates its SVG edge; replace the below-canvas detail board and modal with one accessible right drawer.

**Tech Stack:** Python 3.11 standard library (`sqlite3`, `urllib`, `unittest`), dependency-free WSGI API, vanilla ES modules/CSS/SVG, Docker Compose, DeepSeek JSON Output.

**Spec:** `docs/superpowers/specs/2026-09-28-agent-autofill-drawer-flow-design.md`

## Global Constraints

- DeepSeek never approves a node or calculates formal GEP; only reviewed nodes can enter a snapshot.
- Never persist or display API keys, Authorization headers, full prompts, or raw model responses.
- Default `DEEPSEEK_API_BASE_URL=https://api.deepseek.com` and `DEEPSEEK_MODEL=deepseek-flash`; both remain configurable.
- Only the worker container receives model credentials; the Web bundle and task API do not.
- A model candidate may cite only evidence included in that job's admitted evidence bundle, with an exact SHA-256 match.
- Empty evidence, missing sources, permission limits, and scope conflicts end as `manual_required`, never as zero or a fabricated value.
- Model/network errors end as retryable `agent_failed`; automated retries are out of scope.
- One worker processes jobs in FIFO order; no new runtime dependencies are added.
- SVG flow animation runs only for persisted events and honors `prefers-reduced-motion`.
- The user-approved right drawer supersedes the old below-canvas detail rule in `overleaf/implementation/main.tex`.

## Review Focus

- A malicious model response cites a source outside `allowed_evidence`: reject it and persist no candidate value (Task 2 test).
- A task is opened or auto-scheduled repeatedly: no duplicate current-version jobs are created (Task 3 test).
- A human edits a node while its model request is running: the late result becomes `stale` and does not overwrite the edit (Task 2 regression test).
- An event arrives while its category is collapsed or drawer closed: state updates safely and no animation code throws (Task 5 test).
- A narrow screen, Escape press, or focus return path uses the same drawer without leaving focus trapped or content off-screen (Task 4 browser test).

---

## File Map

- Create `gep/deepseek.py`: HTTP adapter and JSON response parsing only.
- Create `gep/evidence_catalog.py`: resolve admitted evidence for one work order from the selected release package.
- Create `gep/supplement.py`: provider selection and evidence-aware workflow composition.
- Modify `gep/worker.py`: use the provider factory and data root.
- Modify `gep/task_service.py`: generic workflow outcomes, manual-intervention persistence, and idempotent batch enqueue.
- Modify `gep/api.py`: expose batch scheduling without loading model credentials.
- Modify `gep/web/index.html`, `app.js`, `graph.js`, `styles.css`, `api.js`: unified drawer, status copy, and SVG edges.
- Modify `deploy/compose.demo.yml`, `deploy/README.md`: worker-only DeepSeek configuration and secret handling.
- Modify `overleaf/implementation/main.tex`: replace below-page detail wording with the approved drawer behavior and document direct-provider deployment.
- Add or modify focused `tests/` modules listed in each task.

### Task 1: DeepSeek Adapter and Provider Selection

**Files:**
- Create: `gep/deepseek.py`
- Create: `gep/supplement.py`
- Modify: `gep/worker.py`
- Test: `tests/test_deepseek.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `DeepSeekWorkflow.from_environment(environment: Mapping[str, str] | None = None) -> DeepSeekWorkflow | None`
- Produces: `DeepSeekWorkflow.run(work_order: dict[str, Any]) -> dict[str, Any]`
- Produces: `workflow_from_environment(environment: Mapping[str, str] | None = None) -> SupplementWorkflow | None`
- Consumes later: work orders containing `allowed_evidence: list[dict[str, Any]]` from Task 2.

- [ ] **Step 1: Write failing adapter tests**

Add tests proving the adapter posts to `https://api.deepseek.com/chat/completions`, uses `deepseek-flash`, sets `response_format={"type":"json_object"}`, parses `choices[0].message.content`, returns `None` without a key, rejects empty/invalid content, and never includes the supplied key in raised errors.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m unittest tests.test_deepseek tests.test_worker -v`

Expected: FAIL because `gep.deepseek` and `workflow_from_environment` do not exist.

- [ ] **Step 3: Implement the dependency-free DeepSeek adapter**

Use `urllib.request.Request` and `urlopen`; send non-streaming JSON Output with thinking disabled, an explicit JSON-only system instruction, and the serialized work order. Convert 401/403, 429, 5xx, timeouts, empty output, invalid JSON, and invalid response shape into sanitized `RuntimeError`/`ValueError` messages that contain no response body or key.

- [ ] **Step 4: Implement provider selection and switch the worker**

`workflow_from_environment()` selects `deepseek`, `dify`, or `none` from `SUPPLEMENT_PROVIDER`; preserve `DifyWorkflow` behavior. Update `SupplementWorker.run_once()` to use this factory when no workflow is injected.

- [ ] **Step 5: Run focused and regression tests**

Run: `python -m unittest tests.test_deepseek tests.test_dify tests.test_worker -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gep/deepseek.py gep/supplement.py gep/worker.py tests/test_deepseek.py tests/test_worker.py
git commit -m "feat: add DeepSeek supplement provider"
```

### Task 2: Admitted Evidence and Explicit Workflow Outcomes

**Files:**
- Create: `gep/evidence_catalog.py`
- Modify: `gep/supplement.py`
- Modify: `gep/task_service.py`
- Test: `tests/test_evidence_catalog.py`
- Test: `tests/test_task_service.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `EvidenceCatalog(data_root: str | Path).for_work_order(work_order: dict[str, Any]) -> list[dict[str, Any]]`
- Produces: `EvidenceAwareWorkflow(provider: SupplementWorkflow, catalog: EvidenceCatalog).run(work_order: dict[str, Any]) -> dict[str, Any]`
- Extends workflow result contract with `outcome` values `candidate`, `applicability_candidate`, and `manual_required`.
- Consumes: Task 1's `DeepSeekWorkflow` and provider factory.

- [ ] **Step 1: Write failing evidence-catalog tests**

Create a temporary `05_release/reference-2024-v0.1` package containing `observations.json`, `pending.json`, `missing_inputs.csv`, and `manifest.json`. Assert exact matching by region/year/node context, retained source locator and SHA-256, and no match across another year or metric.

- [ ] **Step 2: Write failing outcome/state tests**

Add tests for:

- a valid numeric candidate becoming `candidate_ready/pending_review`;
- a valid applicability candidate setting only `applicability_status` plus `pending_review`;
- `manual_required` setting `acquisition_status=manual_required`, leaving value null, and emitting `supplement.manual_required`;
- an unknown source ID or mismatched hash being rejected;
- an invalid/failed result becoming `agent_failed` without exposing raw response text;
- the existing stale-write test still passing.

- [ ] **Step 3: Run focused tests and confirm failure**

Run: `python -m unittest tests.test_evidence_catalog tests.test_task_service tests.test_worker -v`

Expected: FAIL on the missing catalog and unsupported outcomes.

- [ ] **Step 4: Implement `EvidenceCatalog`**

Load only the selected release directory under `GEP_DATA_ROOT/05_release/<data_version>`, reject path traversal in `data_version`, and normalize records from observations, pending inputs, and the indicator missing-input matrix. Match the stable node key/indicator and known metric aliases; include no raw PDF bytes or unrestricted filesystem paths.

- [ ] **Step 5: Implement `EvidenceAwareWorkflow`**

Attach `allowed_evidence` to a copied work order. If no allowed evidence exists, return `manual_required/source_missing` without calling the provider. After a provider response, require cited source ID and SHA-256 to match one allowed record before returning it to `GepStore`.

- [ ] **Step 6: Extend task-service validation and persistence**

Replace the numeric-only validator with `_workflow_result(payload: Any, node_kind: str) -> dict[str, Any]`. Branch `process_supplement()` by outcome, preserve optimistic version checks, and persist only sanitized explanation/evidence. Keep legacy workflow results without an `outcome` compatible as numeric candidates so existing Dify tests remain valid.

- [ ] **Step 7: Run focused and regression tests**

Run: `python -m unittest tests.test_evidence_catalog tests.test_task_service tests.test_worker tests.test_dify tests.test_delivery -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add gep/evidence_catalog.py gep/supplement.py gep/task_service.py tests/test_evidence_catalog.py tests/test_task_service.py tests/test_worker.py
git commit -m "feat: gate agent outcomes with admitted evidence"
```

### Task 3: Idempotent Automatic Scheduling

**Files:**
- Modify: `gep/task_service.py`
- Modify: `gep/api.py`
- Modify: `gep/web/api.js`
- Test: `tests/test_task_service.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `GepStore.enqueue_all_supplements(task_id: str, scheduler_version: str = "auto-v1") -> dict[str, Any]`
- Produces: `POST /tasks/{id}/supplements:auto -> {queued_count, skipped_count, skipped_by_reason}`
- Consumes: existing `request_supplement(task_id, node_id, idempotency_key)`.

- [ ] **Step 1: Write failing service tests**

Assert that `create_task()` automatically queues every unresolved indicator/input node, skips the preloaded maize quantity candidate, emits `graph.initialized` and `supplement.auto_enqueued`, and creates no duplicates when `enqueue_all_supplements()` is called twice. Include the review-focus case where reopening/scheduling a task at the same node version is idempotent.

- [ ] **Step 2: Write failing API tests**

Assert the new route returns HTTP 202 with counts, rejects an unknown task, and never processes model calls in the request thread.

- [ ] **Step 3: Run focused tests and confirm failure**

Run: `python -m unittest tests.test_task_service tests.test_api -v`

Expected: FAIL because batch scheduling and the route do not exist.

- [ ] **Step 4: Implement transactional batch scheduling**

Generate the idempotency key from scheduler version, task ID, node ID, and node version. Skip category nodes, non-null reviewable values, approved nodes, current queued/running jobs, and terminal not-applicable branches. Return deterministic counts grouped by skip reason.

- [ ] **Step 5: Wire task creation and API route**

Call the domain method after all initial nodes and `graph.initialized` are committed inside task creation. Add the API route and `taskApi.autoSupplement(taskId)` without placing model configuration in `DemoApi`.

- [ ] **Step 6: Run focused and full backend tests**

Run: `python -m unittest tests.test_task_service tests.test_api -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add gep/task_service.py gep/api.py gep/web/api.js tests/test_task_service.py tests/test_api.py
git commit -m "feat: auto-queue unresolved GEP nodes"
```

### Task 4: Unified Right-Side Detail Drawer

**Files:**
- Modify: `gep/web/index.html`
- Modify: `gep/web/app.js`
- Modify: `gep/web/graph.js`
- Modify: `gep/web/styles.css`
- Modify: `tests/web/test_task_canvas.py`

**Interfaces:**
- Produces: `openIndicatorDrawer(node, description)`, `openEvidenceDrawer(node)`, and `closeDrawer({ restoreFocus = true } = {})` in `app.js`.
- Produces: `GepGraph.renderFishbone(indicator, nodes, onNode) -> HTMLElement` sized for the drawer.
- Consumes: existing node/evidence API and review actions.

- [ ] **Step 1: Write failing Web contract tests**

Assert that `index.html` contains one `#detail-drawer` with dialog semantics and no `#detail-board` or `#evidence-dialog`; assert drawer CSS includes a desktop fixed width, mobile full-width rule, transition, and focus-visible styling.

- [ ] **Step 2: Run contract tests and confirm failure**

Run: `python -m unittest tests.web.test_task_canvas -v`

Expected: FAIL because the old below-page board and evidence dialog remain.

- [ ] **Step 3: Replace the old detail containers with one drawer**

Move indicator title, fishbone, evidence result, explanation, source, tool record, method card, and actions into a single `<aside>` drawer. Keep one overlay and one close button; add `aria-modal`, `aria-labelledby`, and a breadcrumb/back action for evidence-to-indicator navigation.

- [ ] **Step 4: Move application behavior to the drawer**

Preserve selected node state, last focused graph button, current indicator context, evidence loading, review, supplement retry, and assistance actions. Close on overlay click or Escape and restore focus when the triggering button still exists.

- [ ] **Step 5: Adapt fishbone rendering and responsive styles**

Remove the large minimum width and below-board layout. Render product branches as a vertical drawer tree; use 420--480 px on desktop and near-full viewport width below 600 px.

- [ ] **Step 6: Run contract and browser checks**

Run: `python -m unittest tests.web.test_task_canvas tests.test_deploy_config -v`

Then run the existing Playwright environment against a local server and assert open/close, Escape, focus return, agriculture-to-field navigation, and a 390 px viewport. Expected: all assertions pass and no runtime errors.

- [ ] **Step 7: Commit**

```bash
git add gep/web/index.html gep/web/app.js gep/web/graph.js gep/web/styles.css tests/web/test_task_canvas.py
git commit -m "feat: move GEP details into a right drawer"
```

### Task 5: SVG Event Flow and Complete Node Statuses

**Files:**
- Modify: `gep/web/graph.js`
- Modify: `gep/web/app.js`
- Modify: `gep/web/styles.css`
- Modify: `tests/web/test_task_canvas.py`
- Modify: `tests/test_deploy_config.py`

**Interfaces:**
- Produces: `GepGraph.layoutEdges() -> void`
- Produces: `GepGraph.animatePersisted(events: Array<TaskEvent>) -> void`
- Produces: stable edge IDs `root:<category>` and `<category>:<indicator>`.
- Consumes: persisted event types from Tasks 2 and 3.

- [ ] **Step 1: Write failing animation/status contract tests**

Assert presence of an SVG edge layer, stable edge IDs, `stroke-dashoffset` animation, persisted event-to-edge mapping, `manual_required` and `agent_failed` labels, and a `prefers-reduced-motion` rule. Assert missing/collapsed edge lookup returns without throwing.

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.web.test_task_canvas tests.test_deploy_config -v`

Expected: FAIL because connections still use CSS borders and statuses are incomplete.

- [ ] **Step 3: Render and relayout SVG connections**

Create the SVG below the node layer, measure the root/category/indicator anchors after render, and draw orthogonal or smooth paths with stable data-edge values. Recompute after zoom, category fold, drawer open/close, and debounced resize.

- [ ] **Step 4: Map persisted events to flow animation**

Animate only `graph.initialized`, queued, running, candidate, manual-required, failed, and stale events. If the edge is absent because a branch is collapsed, update the node state without animation. Do not replay historical events on every reload.

- [ ] **Step 5: Complete state labels and summary counts**

Add distinct UI labels/classes for queued, running, pending review, manual intervention, retryable failure, returned, and approved. Update header/right-rail counts so a completed batch reports pending review, manual intervention, failures, and in-progress work separately.

- [ ] **Step 6: Run Web and full test suite**

Run: `python -m unittest tests.web.test_task_canvas tests.test_deploy_config -v`

Then: `python -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add gep/web/graph.js gep/web/app.js gep/web/styles.css tests/web/test_task_canvas.py tests/test_deploy_config.py
git commit -m "feat: animate persisted GEP task flow"
```

### Task 6: Runtime Configuration and Documentation Synchronization

**Files:**
- Modify: `deploy/compose.demo.yml`
- Modify: `deploy/README.md`
- Modify: `tests/test_deploy_config.py`
- Modify: `/home/wwj/GEP/overleaf/implementation/main.tex`

**Interfaces:**
- Produces: worker-only runtime configuration for `SUPPLEMENT_PROVIDER`, `DEEPSEEK_API_BASE_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, and `DEEPSEEK_TIMEOUT_SECONDS`.
- Consumes: Task 1 provider factory and approved design wording.

- [ ] **Step 1: Write failing deployment tests**

Assert that DeepSeek variables are present only in the worker section, no `sk-` literal appears, Dify compatibility remains, the API receives no model key, and the runtime/data volumes remain unchanged.

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.test_deploy_config -v`

Expected: FAIL because Compose has no DeepSeek configuration.

- [ ] **Step 3: Update Compose and deployment instructions**

Document a `0600` host environment file, no-echo credential entry, worker-only injection, health checks, log-redaction verification, backup, upgrade, and rollback. Do not add a key value or an `.env` file to Git.

- [ ] **Step 4: Synchronize the detailed Overleaf plan**

In the product-requirements section, replace “在下方展开” with the approved right drawer behavior; update the event/status and deployment paragraphs to describe automatic scheduling and direct DeepSeek as the current provider while retaining Dify as an optional adapter. Do not alter formulas or the 22-indicator scope.

- [ ] **Step 5: Verify code docs and LaTeX source**

Run: `python -m unittest tests.test_deploy_config -v`

Run the available Overleaf/LaTeX validation used by this workspace and confirm no new source error. Expected: tests pass and the document builds or reports only pre-existing environment limitations.

- [ ] **Step 6: Commit each repository separately**

Code repository:

```bash
git add deploy/compose.demo.yml deploy/README.md tests/test_deploy_config.py
git commit -m "docs: configure worker-only DeepSeek runtime"
```

Overleaf repository:

```bash
git add implementation/main.tex
git commit -m "docs: update GEP agent drawer workflow"
```

### Task 7: Real DeepSeek Smoke Test, Browser Acceptance, and Deployment

**Files:**
- Create locally outside Git: restricted runtime secret file and disposable smoke-test database.
- Create under ignored/untracked acceptance output: screenshots and sanitized verification summary.
- No source file is modified unless a defect is found; defects return to the owning task and its tests.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a verified release archive, host backup path, deployed release path, health result, sanitized smoke result, and screenshots.

- [ ] **Step 1: Run the complete local suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass with zero failures/errors.

- [ ] **Step 2: Scan tracked content for the provided credential and common key patterns**

Run a redacted scanner that reports filenames/counts only and never prints matching text. Expected: zero tracked matches.

- [ ] **Step 3: Store the key outside Git with no terminal echo**

Create a dedicated `0600` runtime environment file under `/home/wwj/.local/share/gep-deployment/`; enter the value through a no-echo prompt. Verify mode and variable names without printing values.

- [ ] **Step 4: Run a disposable real-API smoke test**

Use a temporary database and the admitted reference package. Verify one evidence-backed work order returns a validated pending-review candidate and one empty/conflicting work order returns manual intervention. Record only job IDs, outcomes, model name, durations, and token counts if available; do not record prompts, raw responses, headers, or key.

- [ ] **Step 5: Run local browser acceptance**

Create a fresh task and verify automatic state transitions, right drawer behavior, evidence view, manual-intervention view, flow animation, refresh recovery, reduced-motion behavior, and mobile layout. Capture sanitized screenshots.

- [ ] **Step 6: Commit any final source fixes and rerun verification**

If acceptance reveals a defect, add a regression test to the owning task, implement the minimal fix, rerun the full suite, and commit the fix. Otherwise make no commit.

- [ ] **Step 7: Back up and deploy a new host release**

Use the existing SSH credential file and release-directory process: back up `/data/wwj/haidian-gep/runtime`, transfer a `git archive` of the verified commit, extract to a new immutable release directory, load the restricted DeepSeek environment into Compose, rebuild, and retain `690284f` for rollback.

- [ ] **Step 8: Perform post-deployment verification**

Verify Compose status, `/api/health`, existing task count, new-task automatic queue, worker progress, right drawer, event-driven flow, and absence of key material in container configuration output, application logs, SQLite, static assets, and export artifacts. Report the exact deployed commit, backup path, release path, tests, real-call outcomes, and remaining data gaps.
