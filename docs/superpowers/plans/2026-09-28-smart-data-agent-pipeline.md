# Smart Data Agent Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one end-to-end 2024 smart-data vertical slice that registers local/online assets, derives auditable observations including AEF model estimates, lets the agent execute allowlisted calculation plans, and presents Demo-versus-formal readiness without exposing indicator nodes as data gaps.

**Architecture:** A new `gep.smart_data` package owns reusable asset, observation, method-plan, execution, and spatial-preparation boundaries. `GepStore` remains the task/evidence system of record and composes `SmartDataStore` over the same SQLite connection; the worker tries direct evidence, reusable observations, then allowlisted estimates before creating consolidated human work. Large raster work stays in an explicit spatial CLI, while API/Web consume metadata and small observations.

**Tech Stack:** Python 3.11+, SQLite, dependency-free WSGI, vanilla JavaScript/CSS, optional spatial build environment (`numpy`, `rasterio`, `scikit-learn`), pytest/unittest, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-28-smart-data-agent-pipeline-design.md`

## Global Constraints

- The accounting mainline is Haidian 2024; 2025-12 through 2026-05 Xuannv assets may be catalogued but cannot satisfy a 2024 input.
- Model estimates may enter **智能试算** when explicitly marked, but cannot make `formal_ready=true`.
- AEF is a 64-dimensional feature source, never a physical GEP quantity without a versioned downstream model.
- The current OSM boundary remains Demo-only and every derived spatial result must carry that limitation.
- DeepSeek receives metadata/summaries only, returns schema-validated plans/explanations, and cannot emit executable code or arbitrary URLs.
- Secrets remain worker-only; no API/Web/database event/static asset/export may contain the DeepSeek key.
- Large rasters/models stay outside Git; Git contains code, small fixtures, manifests, hashes, and quality reports only.
- Existing tasks and `reference-2024-v0.1` are immutable; the new data version is `smart-data-2024-v1`.
- Every database/schema/API change is backward-compatible with the current runtime SQLite file and feature-gated by `GEP_SMART_DATA_ENABLED`.
- TDD is mandatory: each production change follows a failing targeted test, minimal implementation, passing targeted test, full regression, then commit.

## Review Focus

1. **Bottom-up AEF tiles, NoData=-128, overlap, and partial boundary coverage** must either produce one deduplicated masked subset or a precise failed quality report; pinned in Tasks 3–4.
2. **Wrong year/region/unit observations** must never bind to a node even when the metric name matches; pinned in Tasks 1, 5, and 7.
3. **Model plans containing unknown methods, arbitrary code/URLs, missing inputs, or non-finite values** must be rejected without losing deterministic candidates; pinned in Tasks 6–7.
4. **Asset/method changes after a run and concurrent human correction** must mark calculations stale instead of overwriting the node; pinned in Tasks 6–7.
5. **Old databases, disabled feature flag, and existing tasks** must keep working; fresh smart-data tasks must never schedule indicator nodes as research jobs; pinned in Tasks 1, 7, and 9.

---

## File Structure

### New Python package

- `gep/smart_data/__init__.py` — stable public imports only.
- `gep/smart_data/types.py` — validated `AssetRecord`, `ObservationRecord`, `CalculationPlan`, and `CalculationResult` dataclasses.
- `gep/smart_data/store.py` — SQLite schema and CRUD/query methods over an injected connection.
- `gep/smart_data/assets.py` — known-asset scanner and small receipt/manifest parsing.
- `gep/smart_data/aef_pipeline.py` — AEF candidate selection, VRT/window planning, cropping, masking, and quality manifest creation.
- `gep/smart_data/aef_classifier.py` — spatial-block sample preparation, Random Forest training/validation, classification, and area observations.
- `gep/smart_data/observations.py` — MODIS/NASA/DEM/WorldCover aggregation into reusable observations.
- `gep/smart_data/methods.py` — allowlisted smart method definitions and parameter/source rules.
- `gep/smart_data/calculators.py` — pure numeric calculators for the first R1/R2/R6/R7/R10/R4 slice.
- `gep/smart_data/planning.py` — plan validation, deterministic resolver, optional DeepSeek explanation, and safe execution.
- `gep/smart_data/workflow.py` — task-node adapter that returns existing supplement-workflow result shapes.

### New operational/test files

- `scripts/build_smart_data.py` — idempotent spatial/data build CLI.
- `requirements-spatial.txt` — pinned spatial build dependencies, separate from the lean runtime image.
- `tests/fixtures/smart_data/` — tiny synthetic rasters/manifests; no production data.
- `tests/test_smart_data_store.py`
- `tests/test_smart_data_assets.py`
- `tests/test_smart_data_aef.py`
- `tests/test_smart_data_observations.py`
- `tests/test_smart_data_planning.py`
- `tests/test_smart_data_workflow.py`
- `tests/web/test_smart_data_ui.py`

### Existing files to modify

- `gep/task_service.py` — compose smart store, schema migration, input-only scheduling, smart candidate persistence, indicator summaries, dual readiness.
- `gep/supplement.py` — construct smart workflow when enabled.
- `gep/deepseek.py` — add evidence-scoped explanation/plan mode without weakening existing candidate mode.
- `gep/api.py` — smart asset/observation/summary/chain/derive routes.
- `gep/__main__.py` — data-build and scan CLI commands.
- `gep/web/api.js`, `app.js`, `graph.js`, `guide.js`, `index.html`, `styles.css` — smart states, data-backend view, calculation chain, and one-next-action flow.
- `pyproject.toml` — include `gep.smart_data`; keep spatial packages outside runtime dependencies.
- `deploy/compose.demo.yml`, `deploy/README.md` — feature flag, read-only data mount, build/deploy procedure.

---

### Task 1: Smart-data types and backward-compatible persistence

**Files:**
- Create: `gep/smart_data/__init__.py`
- Create: `gep/smart_data/types.py`
- Create: `gep/smart_data/store.py`
- Create: `tests/test_smart_data_store.py`
- Modify: `gep/task_service.py:66-179`
- Modify: `pyproject.toml:18-22`

**Interfaces:**
- Produces: `AssetRecord`, `ObservationRecord`, `CalculationPlan`, `CalculationResult` with `from_dict()` validation and `as_dict()` serialization.
- Produces: `SmartDataStore(connection).register_asset()`, `.list_assets()`, `.asset()`, `.register_observation()`, `.find_observations()`, `.register_plan()`, `.register_run()`, `.calculation_chain()`.
- `GepStore.smart_data` exposes the composed store over the same transaction/connection.

- [ ] **Step 1: Write failing persistence and validation tests**

  Add tests named `test_asset_rejects_non_sha256_and_non_https_remote_source`, `test_observation_requires_finite_value_matching_year_region_and_unit`, `test_registering_same_version_is_idempotent_but_changed_hash_conflicts`, `test_old_database_migrates_without_losing_tasks`, and `test_calculation_chain_preserves_asset_observation_plan_and_run_lineage`. Assert literal values, ordering, and conflict messages.

- [ ] **Step 2: Run the targeted tests and verify RED**

  Run: `/tmp/gep-guided-flow-venv/bin/pytest -q tests/test_smart_data_store.py`
  Expected: collection/import failure because `gep.smart_data` does not exist.

- [ ] **Step 3: Implement validated dataclasses and SQLite schema**

  `AssetRecord` fields match spec §7.1; `ObservationRecord.value` is a finite `int|float`; `CalculationPlan.operations` contains data only; `CalculationResult` always carries input and result hashes. Create tables with `IF NOT EXISTS`, foreign keys, uniqueness on asset/version and observation identity, and no destructive migration.

- [ ] **Step 4: Compose the store into `GepStore` and export package data**

  Initialize `self.smart_data = SmartDataStore(self.connection)` after existing schema creation; update setuptools packages to include `gep.smart_data`.

- [ ] **Step 5: Run targeted and full tests**

  Run targeted command from Step 2, then `pytest -q`.
  Expected: new tests pass; existing 205 tests and 4 subtests remain green.

- [ ] **Step 6: Commit**

  Commit: `feat: add smart data persistence`

---

### Task 2: Known-asset scanning and query API

**Files:**
- Create: `gep/smart_data/assets.py`
- Create: `tests/test_smart_data_assets.py`
- Modify: `gep/api.py:78-190`
- Modify: `gep/__main__.py:8-55`
- Modify: `tests/test_api.py`
- Modify: `gep/web/api.js`

**Interfaces:**
- Consumes: `AssetRecord`, `SmartDataStore.register_asset()` from Task 1.
- Produces: `scan_known_assets(data_root: Path, data_version: str = "smart-data-2024-v1") -> list[AssetRecord]`.
- Produces API: `GET /data-assets`, `GET /data-assets/{asset_id}`, `GET /derived-observations`, trusted `POST /data-assets:scan`.

- [ ] **Step 1: Write failing scanner and API tests**

  Fixtures cover present MODIS/NASA/WorldCover/DEM receipts, a missing file, a symlink escaping the data root, a 2025 asset queried as 2024, and unauthorized scan. Assert missing files become `quality_status="missing"`, symlink escape is rejected, filters are exact, and the API never returns `local_path` outside the approved root.

- [ ] **Step 2: Run targeted tests and verify RED**

  Run: `pytest -q tests/test_smart_data_assets.py tests/test_api.py -k 'data_asset or observation'`
  Expected: route/function failures.

- [ ] **Step 3: Implement receipt-driven scanning**

  Read only known catalog/receipt paths; calculate SHA-256 for small receipts and use recorded hashes for large admitted rasters after existence/size checks. Map MODIS 2024, NASA POWER, WorldCover, two DEM tiles, AEF index, official facts, and Xuannv comparison assets without treating Xuannv as a 2024 observation.

- [ ] **Step 4: Implement filtered APIs and CLI `smart-data-scan`**

  Parse query strings for `asset_type`, `year`, `quality_status`, `metric`, and `region_code`; scan requires the trusted custodian header. Extend `taskApi` with read methods only; UI use comes in Task 9.

- [ ] **Step 5: Verify targeted and full suites, then commit**

  Expected: deterministic asset ordering and no regression.
  Commit: `feat: expose smart data asset catalog`

---

### Task 3: Safe 2024 AEF acquisition and Haidian subset build

**Files:**
- Create: `gep/smart_data/aef_pipeline.py`
- Create: `scripts/build_smart_data.py`
- Create: `requirements-spatial.txt`
- Create: `tests/fixtures/smart_data/aef/` (tiny 64-band Int8 fixture, VRT, boundary)
- Create: `tests/test_smart_data_aef.py`
- Modify: `gep/__main__.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `AssetRecord`, existing `validate_boundary()`, `select_2024_assets()`, `dequantize_int8()`.
- Produces: `plan_aef_subset(index_path: Path, boundary: dict, year: int = 2024) -> AefSubsetPlan`.
- Produces: `build_aef_subset(plan: AefSubsetPlan, output_dir: Path) -> AefSubsetResult` with COG/VRT paths, hashes, coverage, band metadata, attribution, and quality status.

- [ ] **Step 1: Write failing geometry/storage tests**

  Include tests for three overlapping candidates, bottom-up source corrected through VRT, NoData propagation, a boundary crossing two tiles, partial coverage, HTTP failure leaving no registered output, duplicate dequantization refusal, and output paths outside `output_dir`. Assert 64 bands, 10 m, EPSG:32650, deduplicated pixel count, atomic result, and CC-BY attribution literal.

- [ ] **Step 2: Run spatial tests and verify RED**

  Create `/tmp/gep-smart-data-venv`, install project plus `requirements-spatial.txt`, then run `pytest -q tests/test_smart_data_aef.py`.
  Expected: missing pipeline failures.

- [ ] **Step 3: Implement planning and range/window acquisition**

  Use Source Cooperative companion VRT URLs derived from the three index paths, `rasterio` window reads/merge/mask, a temporary directory, and atomic rename. Preserve signed Int8; do not materialize a float 64-band cube.

- [ ] **Step 4: Implement CLI and manifests**

  `python scripts/build_smart_data.py aef --data-root ... --boundary ... --year 2024` writes the subset and a small JSON quality manifest. Add large output directories to `.gitignore` without ignoring manifests under `data/catalog`.

- [ ] **Step 5: Verify spatial tests, non-spatial full suite, and secret/large-file scan**

  Assert no file over 5 MiB is staged and no `sk-` credential occurs in tracked changes.

- [ ] **Step 6: Commit**

  Commit: `feat: build 2024 AlphaEarth subset`

---

### Task 4: Weakly supervised AEF classification and area observations

**Files:**
- Create: `gep/smart_data/aef_classifier.py`
- Extend: `tests/test_smart_data_aef.py`
- Modify: `scripts/build_smart_data.py`

**Interfaces:**
- Consumes: `AefSubsetResult`, WorldCover raster, Demo boundary, `SmartDataStore.register_observation()`.
- Produces: `train_aef_classifier(aef_path, labels_path, boundary_path, output_dir, random_seed=20240928) -> AefModelResult`.
- Produces: `classify_aef(model_result, aef_path, output_dir) -> AefClassificationResult` including macro-F1, per-class recall/IoU, confidence coverage, area table, hashes, and `auto_usable`.

- [ ] **Step 1: Write failing model-quality tests**

  Synthetic spatial blocks must prove the holdout blocks never appear in training. Test pass at macro-F1=0.70/all key recalls=0.50, fail below either boundary, fail on class/CRS misalignment, and downgrade when official-area reconciliation differs by more than 20%.

- [ ] **Step 2: Run tests and verify RED**

  Run: `/tmp/gep-smart-data-venv/bin/pytest -q tests/test_smart_data_aef.py -k classifier`.

- [ ] **Step 3: Implement deterministic sampling/training/validation**

  Use fixed-seed Random Forest, class-balanced sampling, grid-based spatial holdout, and joblib-free pickle only inside the data root. Hash sample indices, parameters, model, classification raster, and report.

- [ ] **Step 4: Emit ecosystem-area observations**

  Register each area as metric `ecosystem_area`, year 2024, unit `hm2`, evidence class `model_estimate`; attach class code/name, model hash, validation metrics, Demo-boundary limitation, and source asset IDs.

- [ ] **Step 5: Verify, review output schema, and commit**

  Commit: `feat: derive ecosystem areas from AlphaEarth`

---

### Task 5: MODIS, climate, terrain, and cover observation builders

**Files:**
- Create: `gep/smart_data/observations.py`
- Create: `tests/test_smart_data_observations.py`
- Extend: `scripts/build_smart_data.py`

**Interfaces:**
- Consumes: data assets and `SmartDataStore.register_observation()`.
- Produces: `build_nasa_power_observations()`, `build_modis_observations()`, `build_terrain_observations()`, `build_cover_observations()` returning `list[ObservationRecord]`.

- [ ] **Step 1: Write failing observation tests**

  Assert 2024 precipitation equals the literal sum of the twelve fixture months; ET requires all 46 periods and QC metadata; NPP remains `npp` and never becomes `nep`; DEM overlap is mosaicked once; cover areas sum to the masked boundary within one pixel; wrong year, region, unit, NaN, incomplete months, and missing source assets are rejected or downgraded with exact reason codes.

- [ ] **Step 2: Run tests and verify RED**

  Run: `/tmp/gep-smart-data-venv/bin/pytest -q tests/test_smart_data_observations.py`.

- [ ] **Step 3: Implement chunked builders and CLI `observations` stage**

  Read rasters in windows, transform masks by CRS, and store only aggregate observations plus artifact references. Evidence classes: MODIS/DEM calculations `public_calculation`; NASA single-point and WorldCover-derived values `model_estimate`.

- [ ] **Step 4: Verify unit/range lineage and commit**

  Run spatial targeted tests and the dependency-free full suite.
  Commit: `feat: derive 2024 smart observations`

---

### Task 6: Versioned methods, calculators, plan validation, and safe execution

**Files:**
- Create: `gep/smart_data/methods.py`
- Create: `gep/smart_data/calculators.py`
- Create: `gep/smart_data/planning.py`
- Create: `tests/test_smart_data_planning.py`

**Interfaces:**
- Consumes: `ObservationRecord`, Task 1 plan/run persistence.
- Produces: `SMART_METHODS: dict[str, SmartMethod]` for `R1.water_balance.demo.v1`, `R2.spatial_factors.demo.v1`, `R6.npp_conversion.demo.v1`, `R7.oxygen_link.demo.v1`, `R10.local_climate.demo.v1`, `R4.inland_applicability.demo.v1`.
- Produces: `resolve_plan(work_order, observations, provider=None) -> CalculationPlan | None`.
- Produces: `execute_plan(plan, observations) -> CalculationResult`.

- [ ] **Step 1: Write failing calculator and hostile-plan tests**

  Pin hand-calculated fixture outputs and unit conversions. Reject unknown method/version, missing/wrong-year inputs, duplicate binding, non-finite input/output, arbitrary operation/code/URL keys, unit mismatch, and a parameter not backed by an observation/source. Confirm provider failure still returns the deterministic plan with fallback explanation.

- [ ] **Step 2: Run tests and verify RED**

  Run: `pytest -q tests/test_smart_data_planning.py`.

- [ ] **Step 3: Implement pure calculators and allowlisted registry**

  Calculators accept named finite quantities and return a typed result only. The registry defines required metrics/units, allowed evidence classes, formula text, applicability, and output unit; no `eval`, dynamic import, or generated code.

- [ ] **Step 4: Implement resolver, schema validation, hashes, and stale detection**

  Compute input/parameter manifests canonically. Before persistence, compare node version and observation/asset versions; stale results remain audit records but are not applied.

- [ ] **Step 5: Verify targeted/full suites and commit**

  Commit: `feat: execute allowlisted smart calculations`

---

### Task 7: Agent workflow and task-graph integration

**Files:**
- Create: `gep/smart_data/workflow.py`
- Create: `tests/test_smart_data_workflow.py`
- Modify: `gep/supplement.py:23-51`
- Modify: `gep/deepseek.py:11-96`
- Modify: `gep/research.py:24-140`
- Modify: `gep/task_service.py:260-310, 760-875, 980-1100`
- Modify: `tests/test_task_service.py`, `tests/test_research.py`, `tests/test_worker.py`

**Interfaces:**
- Consumes: `SmartDataStore`, `resolve_plan()`, `execute_plan()`.
- Produces: `SmartDataWorkflow.run(work_order) -> dict` compatible with `GepStore.process_next_supplement()`.
- Produces: `GepStore.indicator_progress(task_id) -> dict[str, dict]` and smart candidate result classes `public_calculation`, `model_estimate`, `needs_department_data`, `needs_business_decision`, `not_applicable_candidate`.

- [ ] **Step 1: Write failing workflow/scheduler tests**

  Assert a new smart-data task queues only unresolved input nodes; 22 indicators receive aggregate progress and never `research_complete`. Test observation reuse, calculated candidate, model estimate auto-entry into Demo, R4 not-applicable candidate, consolidated human reasons, provider outage, stale calculation after human revision, idempotent rerun, and feature flag off preserving the old workflow.

- [ ] **Step 2: Run tests and verify RED**

  Run: `pytest -q tests/test_smart_data_workflow.py tests/test_task_service.py -k 'smart or indicator_progress'`.

- [ ] **Step 3: Implement workflow selection and explanation mode**

  When enabled and data version is `smart-data-2024-v1`, compose `SmartDataWorkflow`; otherwise preserve current `ResearchWorkflow`. Add a DeepSeek explanation prompt that receives only the validated plan and evidence summary and cannot change numeric output/method/input IDs.

- [ ] **Step 4: Persist result classes and aggregate indicators**

  Map smart outputs into existing node/evidence/event versioning. Keep formal review status separate from Demo usability. Group identical missing department/decision requirements by reason and source owner in automation summary.

- [ ] **Step 5: Verify targeted/full suites, scan secret surfaces, and commit**

  Commit: `feat: run smart data agent workflow`

---

### Task 8: Dual readiness, Demo snapshot, and audit APIs

**Files:**
- Modify: `gep/task_service.py:310-480, 1100-1245`
- Modify: `gep/api.py:143-190`
- Modify: `tests/test_task_service.py`, `tests/test_api.py`, `tests/test_runs.py`

**Interfaces:**
- Consumes: smart result classes and calculation chains from Tasks 1/7.
- Produces: `GepStore.automation_summary(task_id)`, `.demo_readiness(task_id)`, `.formal_readiness(task_id)`, `.create_demo_snapshot(task_id)`.
- Produces API: `GET /tasks/{id}/automation-summary`, `GET /tasks/{id}/demo-readiness`, `GET /nodes/{id}/calculation-chain`, `POST /tasks/{id}/demo-snapshots`.
- Readiness payloads expose explicit booleans `demo_ready` and `formal_ready`; an estimate may affect only the former.

- [ ] **Step 1: Write failing dual-gate tests**

  Model estimates and public calculations make their populated inputs Demo-usable but not formal-ready. Missing department data and business decisions remain explicit. A formal snapshot path is unchanged. Demo exports include `result_scope="智能试算"`, estimated-input ratio, every calculation-chain hash, and `formal_gep_value=null` unless formal readiness passes.

- [ ] **Step 2: Run tests and verify RED**

  Run: `pytest -q tests/test_task_service.py tests/test_api.py tests/test_runs.py -k 'demo or formal_readiness or calculation_chain'`.

- [ ] **Step 3: Implement separate readiness and snapshot methods/routes**

  Reuse current graph version/conflict checks; never mutate formal approvals when making a Demo snapshot.

- [ ] **Step 4: Verify audit exports/full suite and commit**

  Commit: `feat: separate demo and formal readiness`

---

### Task 9: Smart states, data-backend UI, and guided human work

**Files:**
- Create: `gep/web/smart-data.js`
- Create: `tests/web/test_smart_data_ui.py`
- Modify: `gep/api.py:74-75` (serve asset)
- Modify: `gep/web/api.js`
- Modify: `gep/web/index.html:42-80`
- Modify: `gep/web/app.js:27-269`
- Modify: `gep/web/graph.js:42-55, 72-103, 151-186`
- Modify: `gep/web/guide.js`
- Modify: `gep/web/styles.css`
- Modify: `tests/web/test_task_canvas.py`, `tests/web/test_guided_browser_ux.py`

**Interfaces:**
- Consumes: new APIs and summary/status shapes.
- Produces: `renderAssetCatalog(container, assets, observations)`, `renderCalculationChain(container, chain)`, smart node labels, indicator progress, and one primary next action.

- [ ] **Step 1: Write failing real-browser tests**

  Mock complete API payloads and assert: `指标图/数据后台` tabs; filters; asset quality/period/hash/license; model-estimate labels; indicator `7/8 已自动准备`; no indicator text `已自动检索·等待数据`; a calculation drawer with inputs/formula/parameters/output/uncertainty; consolidated human-work cards; Demo/formal badges; one visible primary CTA; mobile 390 px body has no horizontal overflow.

- [ ] **Step 2: Run browser tests and verify RED**

  Run with Playwright environment: `pytest -q tests/web/test_smart_data_ui.py`.

- [ ] **Step 3: Implement API client, tabs, summaries, and drawer chain**

  Keep the existing right drawer and continuous edge flow. Large canvas may scroll internally; asset list and human cards must be keyboard accessible.

- [ ] **Step 4: Implement status/copy and next-action rules**

  Exact visible states: `自动采用`, `公开数据计算`, `模型估算·已进入试算`, `建议复核`, `等待部门数据`, `需要业务判断`, `不适用候选`, `执行失败·可重试`.

- [ ] **Step 5: Verify all browser and full tests; capture screenshots/video; commit**

  Commit: `feat: add smart data workbench UI`

---

### Task 10: Real 2024 data build, host deployment, and rollback proof

**Files:**
- Modify: `deploy/compose.demo.yml`
- Modify: `deploy/README.md`
- Modify: `docs/validation.md`
- Create/update small generated manifests under `/home/wwj/GEP/data/catalog/` (outside the code repository; never stage large data)

**Interfaces:**
- Consumes: all prior CLI/API/UI interfaces.
- Produces: admitted `smart-data-2024-v1` assets/observations on the host and immutable deployed release.

- [ ] **Step 1: Add deployment tests before changing compose/docs**

  Assert `GEP_SMART_DATA_ENABLED`, worker-only DeepSeek key, read-only data mount, no spatial dependency in API/Web image, 9088 loopback binding, and rollback instructions.

- [ ] **Step 2: Build real local data in stages**

  Run scan, AEF subset, classifier, and observations against `/home/wwj/GEP/data/haidian_gep_2024`. Save command logs without credentials. Verify hashes, 2024 period, coverage, 64 bands, 10 m, validation thresholds, finite observations, and license receipts.

- [ ] **Step 3: Run complete local verification**

  Run non-spatial full suite, spatial suite, `git diff --check`, source/secret/large-file scans, and real browser flow. Record exact counts and data-quality results.

- [ ] **Step 4: Commit code/docs and push the feature branch**

  Commit: `docs: validate smart data pipeline`

- [ ] **Step 5: Back up host and deploy immutable release**

  Back up SQLite, upload code release plus approved data manifests/derived artifacts to the existing data root, load the restricted DeepSeek env only for worker, build Compose, and health-check `/api/health` through 9088.

- [ ] **Step 6: Run host acceptance and rollback audit**

  Create a fresh `smart-data-2024-v1` task; verify assets, smart workflow, indicator progress, R1/R2/R4/R6/R10 chains, Demo/formal separation, refresh recovery, browser console, and credential scope. Prove previous release path and matching runtime backup remain available.

- [ ] **Step 7: Merge to main and push GitHub after acceptance**

  Re-run the full suite on merged main, push, remove the feature worktree, and report commit, release path, backup path, test counts, data-quality caveats, and 9088 access instructions.
