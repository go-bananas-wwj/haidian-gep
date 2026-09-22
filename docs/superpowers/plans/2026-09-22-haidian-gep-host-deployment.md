# 海淀区 2024 全口径 GEP Demo 实施与宿主机部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在宿主机交付一个按《GEP 智能核算详细实施方案》约束、可追溯、可恢复且不把缺失数据伪装为正式总 GEP 的海淀区 2024 年度全口径 GEP 系统。

**Architecture:** Web 画布经任务服务维护版本化图、证据、审核和事件；异步补充服务仅把有结构化证据的结果写为候选；确定性引擎只接收审核快照并把 DAG、运行、调整和导出包固化到文件卷。SQLite（WAL）保存事务性索引，原件、栅格、运行产物与可交付证据包均保存于独立持久化目录。Dify 是可选的内部工作流编排层，不是事实或公式的权威来源。

**Tech Stack:** Python 3.12、标准库/FastAPI 级 HTTP 服务、SQLite WAL、GDAL/Rasterio/GeoPandas 专用地理镜像、静态 Web 画布、Docker Compose、Nginx、Dify 官方完整 Compose。

**Spec:** `/home/wwj/GEP/overleaf/implementation/main.tex` at `053f22937a7728ca9ebe8ea44222ef999b7b9067` (remote `main` verified equal on 2026-09-22).

## Global Constraints

- 空间范围为海淀区 110108 全行政区域；核算期为 `[2024-01-01, 2025-01-01)` 共 366 天（方案 §1、§2、§4）。
- 全部三类 22 科目必须分别有“已核算 / 不适用 / 已核实为零 / 待补数据”结论；缺失绝不自动变为零或全口径总 GEP（§1、§3、§11）。
- AlphaEarth 仅用于 2024 分类与参数分区，64 维、方向修正、掩膜、解量化、覆盖、标签留出验证都必须可追溯；它不替代 NPP、ET、价格、成本或调查数据（§2）。
- 人工审核绑定节点当前版本；修正保留原值、证据和影响范围；正式计算只读取冻结且审核通过的快照（§7--§9）。
- LLM/Dify 不可用、资料失败或权限不足时保留缺口或错误；不得生成模拟候选值或虚构执行记录（§7、§8）。
- 密钥只经受限运行环境注入；不得写入 Git、镜像层、SQLite 导出、日志、证据包或前端（§6、§12）。
- 不占用、替换或修改宿主机既有服务。2026-09-22 已观测到 8000、8080、8123 有 HTTP 服务，故未获批准前不按示例直接绑定 8000/8080。
- Git 作者和提交者固定为 `go-bananas-wwj <wuweijie25@mails.ucas.ac.cn>`；只在用户批准的实现阶段提交与推送（Prompt §5）。

## Current Evidence and Non-Claims

| Requirement / source section | Current evidence | Status and implication |
|---|---|---|
| §1 full area, 366 days, 22 indicators | `05_release/reference-2024-v0.1/missing_inputs.csv` lists P1--P7, R1--R12, C1--C3 all pending | No complete accounting conclusion; formal total must remain blocked. |
| §2 AlphaEarth annual base | `00_catalog/aef_2024_candidate_tiles.json` contains three bbox candidates using an unconfirmed OSM demo boundary; `03_features/` is empty | Index/candidates are not selected assets, local COG/VRT, 64-dimensional features, or coverage QA. |
| §2 yearbook reference | `quality_report.json`: 43 rows, 40 observed, 2 blank, 1 scope conflict; maize 2935.1 t is table 5-11 printed p.71 | Real source usable only as an input observation; price/cost and full P1 product accounting are missing. |
| §7--§9 first software loop | branch `feature/haidian-gep-demo-core`, commit `f70c2d6`; 27 unit/HTTP tests passed on 2026-09-22 | Existing code proves task creation, 22 indicator shells, maize evidence, review/version conflict, correction provenance, idempotent blocked supplement and snapshot blocking. It does not implement formulas, runs, exports, map, Dify, or identity provider. |
| §12 host readiness | Host `K0703`: Ubuntu 22.04, 112 CPUs, 503 GiB RAM (about 444 GiB available), root free about 1.5 TiB, `/data` free about 3.7 TiB, Docker 29.8, Compose 5.5, eight RTX 4090 GPUs (24 GiB each) | Compute capacity is sufficient for processing; no Dify Compose is present. Existing `4090wwj` container and listeners must remain untouched. |
| §12 location and ports | `/srv` is root-owned; `/data/wwj` is user-owned. `8000` returns 200 and `8080` returns 302 locally | Deployment path and ingress are pending approval: obtain working sudo for `/srv/haidian-gep`, or approve `/data/wwj/haidian-gep`; choose a reverse-proxy route or approved unused ports. |

## Review Focus

1. A blank source field, an unconfirmed boundary, or a non-finite value must remain a blocker rather than becoming zero; Task 1 and Task 4 tests own this.
2. An expired review, duplicate supplement request, or concurrent correction must not overwrite a newer candidate; Task 5 tests own this.
3. A price-only revision must invalidate only affected value/downstream nodes, while a boundary change invalidates all spatial dependents; Task 7 tests own this.
4. A Dify/model outage, source permission error, or malformed tool response must persist an explainable failed/blocked job and never fabricate an observation; Task 6 tests own this.
5. An archive restore must reproduce a frozen run and its evidence at relative error `<= 1e-6`, and never silently use mutable raw files; Task 10 tests own this.

## File and Service Map

| Area | Create or modify | Responsibility |
|---|---|---|
| Data governance | `data/haidian_gep_2024/00_catalog/indicator_catalog.csv`, `field_matrix.csv`, `annual_rules.csv`, `adjustments.csv`, `data_manifest.csv`, `qa/` | 22-item applicability, required inputs, units, source/permission/hash, 2024 rules and QA. |
| Geospatial pipeline | `gep/geo/alphaearth.py`, `gep/geo/coverage.py`, `gep/geo/classify.py`, `tests/test_alphaearth.py` | Asset selection, local VRT, orientation, Int8 conversion, coverage and held-out validation. |
| Formula engine | `gep/formulas/registry.py`, `gep/formulas/*.py`, `gep/runs.py`, `tests/test_formulas_*.py` | Method cards, unit conversion, physical/value calculations, adjustment ledger, DAG cache and run chain. |
| Task domain/API | extend `gep/task_service.py`, `gep/api.py`, add `gep/identity.py`, `gep/worker.py`, `tests/test_api.py`, `tests/test_task_service.py` | Versioned task graph, trusted identity, jobs/events, snapshots, run/export contracts. |
| Web | replace `gep/web/index.html` with bundled application assets under `gep/web/` | Five pages, canvas/detail view, evidence, review, blocked state, map/result/export links; layout state remains non-accounting data. |
| Deployment | `deploy/compose.*.yml`, `deploy/nginx.conf`, `deploy/.env.example`, `deploy/systemd/`, `deploy/README.md`, `Dockerfile*` | Isolated networks/volumes, reverse proxy integration, backup/restore and fixed image/version records. |
| Delivery | `scripts/export_delivery.py`, `scripts/verify_delivery.py`, `docs/appendix-d-template.md`, `docs/demo-script.md` | Appendix D/E, checksums, screenshots, replay, recovery and measured acceptance results. |

### Task 1: Freeze the real input contract and data-admission gate

**Files:**
- Create: `data/haidian_gep_2024/00_catalog/indicator_catalog.csv`, `field_matrix.csv`, `annual_rules.csv`, `adjustments.csv`, `data_manifest.csv`
- Create: `gep/admission.py`, `tests/test_admission.py`
- Modify: `gep/catalog.py`, `gep/task_service.py`

**Interfaces:**
- Consumes: normalized source records with `{region_code, year, source_id, value, unit, status, sha256}`.
- Produces: `AdmissionResult(accepted: bool, blockers: list[AdmissionBlocker])` and one immutable data-version manifest.

- [ ] Write failing tests for a 2023 field, blank value, `NaN`, unreviewed source, duplicate product ownership, and a missing price/cost field; each must return its stable node ID as a blocker.
- [ ] Run `python -m unittest tests/test_admission.py -v` and confirm the missing admission API fails.
- [ ] Implement exact 2024/110108 checks, finite numeric checks, permitted units, source hash/permission checks, 22-item applicability state, and external/overlap adjustment IDs. Keep 2024 yearbook observations as observations, not value inputs.
- [ ] Import the 43 existing records without rewriting raw data; write the resulting manifest hash and a missing-input matrix whose 22 rows match the standard catalogue.
- [ ] Run all admission tests and `python -m gep check .../yearbook_2024_selected.csv`; commit `feat: add GEP data admission contract`.

### Task 2: Acquire and validate the 2024 spatial base before using it

**Files:**
- Create: `gep/geo/alphaearth.py`, `gep/geo/coverage.py`, `scripts/acquire_alphaearth.py`, `tests/test_alphaearth.py`
- Create: versioned files beneath `01_raw/remote_sensing/alphaearth_2024/`, `02_clean/spatial/`, `03_features/`, `qa/alphaearth/`

**Interfaces:**
- Consumes: approved administrative boundary, Source Cooperative index/README, selected 2024 COG/VRT assets.
- Produces: local-only VRT/COG set, selected-assets parquet/CSV, coverage report and 64-band feature manifest.

- [ ] Obtain and review an authoritative 2024 boundary; reject the current `unconfirmed_osm_demo_boundary` for formal processing.
- [ ] Write failing tests using a small Int8 fixture: `-128` becomes NoData, valid data maps by `sign(q) * (q/127.5)^2`, output is float, and a second conversion is rejected.
- [ ] Implement intersection over the index CRS, asset selection over all intersections, VRT source replacement with local COG paths, orientation verification, hash/CRS/affine capture, and no-network-read check.
- [ ] Download resumably only after disk forecast and source license receipt; compute per-tile valid area, overlaps, holes and 64-dimension completeness against the approved boundary. Fail admission when area error exceeds 0.5%.
- [ ] Train/evaluate a light classifier only with recorded labels and spatially disjoint holdout folds; save model card, class mapping, seed, metrics and uncertainty mask. Commit `feat: validate annual AlphaEarth base`.

### Task 3: Complete source acquisition and method cards for all 22 indicators

**Files:**
- Create: `data/haidian_gep_2024/02_clean/{agriculture,water,environment,culture,prices}/`
- Create: `data/haidian_gep_2024/00_catalog/method_cards/`
- Create: `docs/data-requests/` with field-specific request templates
- Modify: `field_matrix.csv`, `method_sources.csv`, `missing_inputs.csv`

**Interfaces:**
- Consumes: department records, surveys, NPP/ET/QC, ERA5-Land, DEM/soil, source receipts and approved boundary.
- Produces: field-level data cards with source locator, unit conversion, permission, QC, method, validation and de-duplication decision.

- [ ] Make one method card for each P1--P7, R1--R12 and C1--C3 using GB/T clause/table locations quoted in §3; identify object, formula, input fields, spatial support, price basis, applicability and validation method.
- [ ] Send/track requests for production quantity/price/cost, water routes/flows, pollution/emission/monitoring, hydrologic/respiration drivers, noise observations, cultural-use survey and landscape premium data. Preserve replies/attachments and access restrictions.
- [ ] Process MOD17 NPP/QC, MOD16 ET/QC, 12 months ERA5-Land and DEM/soil into independently versioned physical inputs; record scales, QC loss, leap-day handling and parameter sources.
- [ ] Resolve P4 only with actual harvest or a reviewed estimate, resolve R4 only with boundary-backed non-applicability, and never promote the `60 t` teaching sample or maize teaching price/cost to real data.
- [ ] Conduct field-level QA, price-year normalization to 2024, and source hash/permission review; freeze only a data version that passes Task 1. Commit `data: freeze audited 2024 input version` only after human domain approval.

### Task 4: Implement deterministic GB/T calculation and accounting ledger

**Files:**
- Create: `gep/formulas/{registry,material,regulating,cultural,units,adjustments}.py`, `gep/runs.py`
- Create: `tests/test_formulas_{material,regulating,cultural,ledger}.py`

**Interfaces:**
- Consumes: `FrozenSnapshot`, method card ID, reviewed input versions and data manifest.
- Produces: `RunResult` with item physical/value result, adjustment ledger, category subtotals, GEP and input/output hashes.

- [ ] Write the failing unit tests for the standard’s manual carbon calculation and 325万元 ledger sample; cover `t/a`, `m3/a`, `person-visits/a`, yuan/ten-thousand-yuan, negative residual, leap day, blank and duplicate accounting paths.
- [ ] Implement a registry keyed by indicator and approved method version. Each function must declare typed input IDs, output unit, applicability predicate, GB/T locator and explicit uncertainty/estimate label.
- [ ] Implement P1--P7 residual value formula and product-level uniqueness; implement R1--R12 and C1--C3 only when their method-card inputs exist. Return blocker objects instead of fallback values.
- [ ] Implement `Adjustment` entries with unique ID, source/overlap reason, amount, booking location and evidence. Enforce exactly-once deduction across P1/R12, P5/R1 and C1/C2/C3 choices.
- [ ] Verify three category sums, external and overlap deductions, `<=1e-6` replay tolerance, and Appendix-E rows against manually reviewed samples. Commit `feat: add deterministic GB/T formula engine`.

### Task 5: Extend the task API into a complete durable execution contract

**Files:**
- Modify: `gep/task_service.py`, `gep/api.py`, `gep/server.py`
- Create: `gep/identity.py`, `gep/worker.py`, `tests/test_runs.py`, `tests/test_identity.py`

**Interfaces:**
- Consumes: API contracts in scheme §8.2 and trusted proxy principal/role headers.
- Produces: `/tasks`, graph/events/evidence/revision/review/snapshot, `/runs`, run chain, run revision and export endpoints.

- [ ] Add failing HTTP tests for every scheme route, expected-version 409, idempotency replay, event resumption after a sequence number, permission denial, and snapshot refusal where any applicable required field is unreviewed.
- [ ] Replace header-only demo identity with a reverse-proxy verified principal plus server-side role lookup; reject missing/forged identity and record authenticated actor/role in audit records.
- [ ] Persist `Task`, `GraphNode`, `NodeVersion`, `Evidence`, `SupplementJob`, `Review`, `Snapshot`, `Run`, `Adjustment` and `Event`; retain immutable node/run evidence and separate personal view state.
- [ ] Submit approved snapshots to a recoverable worker queue. Implement queued/running/succeeded/failed/blocked transitions, parent run references and content-hash cache keys.
- [ ] Run API/concurrency/restart tests against two SQLite connections and a restarted server; commit `feat: add durable calculation run API`.

### Task 6: Connect real supplement tooling and Dify without simulated facts

**Files:**
- Create: `gep/supplement/{contracts,local_catalog,workflow_client}.py`, `tests/test_supplement.py`
- Create: `deploy/dify/README.md`, `deploy/dify/versions.lock`
- Modify: `deploy/compose.*.yml`, `deploy/.env.example`

**Interfaces:**
- Consumes: node work order `{region, year, indicator, field, source scope, question}` and real tool output with source identifiers.
- Produces: candidate record with evidence/explanation, or durable blocked/failed job.

- [ ] Write failing tests proving a model timeout, permission failure, unstructured response or citation without a stored source cannot create a candidate value.
- [ ] Implement local catalogue lookup first, then registered acquisition tools; schema-validate numeric/unit/year/region/source hash before persisting a candidate.
- [ ] Retrieve a pinned, official Dify Compose release only after model gateway, credential storage and internal-network decision are supplied; record release tag, images and workflow export hash.
- [ ] Configure the business API as an internal Dify tool, not `localhost`; keep upload/download/geo tools least-privileged and hold human-review pauses in the business database.
- [ ] Verify one true local maize lookup, one missing P4/R1 request, retry/idempotency and restart recovery; commit `feat: add evidence-gated supplement workflow`.

### Task 7: Deliver the five-page task canvas, map and result evidence

**Files:**
- Replace: `gep/web/index.html`
- Create: `gep/web/{app.js,api.js,graph.js,styles.css,map.js}` and browser tests under `tests/web/`

**Interfaces:**
- Consumes: durable graph/events/evidence/run/export API responses.
- Produces: task centre, graph/detail view, freeze/execute/review, results/map and delivery pages.

- [ ] Write browser/API contract tests for 22 fixed indicators, product-detail switch persistence, reconnecting from an event sequence, node-version conflict display, and no evidence-free “completed” label.
- [ ] Render the five specified pages: task centre, task graph/review, scheme confirmation, execution/result review, and result/Appendix-E/evidence page. Make category/detail templates indicator-specific.
- [ ] Implement canvas zoom/collapse/layout persistence separately from accounting input versions; events animate only after server persistence.
- [ ] Surface source table snippets, locator, extraction explanation, tool run, correction/return history, method/uncertainty and all blockers. Add upload/estimate/defer actions without bypassing review.
- [ ] Render spatial values only where supported and separate non-spatial district totals. Measure warm page target over ten requests. Commit `feat: deliver evidence-first GEP task canvas`.

### Task 8: Build deployment artifacts around the approved host ingress

**Files:**
- Modify: `Dockerfile`, `deploy/compose.demo.yml`, `deploy/nginx.conf`, `deploy/README.md`
- Create: `deploy/{compose.production.yml,.env.example,backup.sh,restore.sh,healthcheck.sh,version-record.sh}`

**Interfaces:**
- Consumes: approved host root, external route/ports, TLS/auth proxy, data root, Dify internal network, image digests.
- Produces: repeatable compose deployment with named volumes, health checks and documented start/stop/rollback.

- [ ] Do not start this task until the user approves either (a) a sudo-created `/srv/haidian-gep` root or (b) the documented `/data/wwj/haidian-gep` deviation, and specifies the ingress path or unused approved ports.
- [ ] Write Compose validation tests that fail if runtime/database/evidence/log/backup storage is ephemeral, an API is publicly bound unintentionally, two processes write one SQLite database, or a secret is copied into an image.
- [ ] Build pinned application and geospatial images, run dependency/GDAL/PROJ/Rasterio compatibility checks, record image digests, and attach read-only source data plus separate writable runtime volumes.
- [ ] Place Nginx/auth proxy in front of Web/API according to approved ingress; remove spoofed identity headers before injecting verified principal headers. Keep Dify on an internal Docker network.
- [ ] Test start, health, stop, restart, backup and restore on the host without modifying existing `4090wwj` or services. Commit `ops: add reproducible host deployment`.

### Task 9: Freeze reports, exports and a truthful demonstration package

**Files:**
- Create: `scripts/{export_delivery,verify_delivery}.py`, `docs/{appendix-d-template,demo-script}.md`
- Create at runtime: `exports/haidian-demo-v0.1/` according to scheme §9.3

**Interfaces:**
- Consumes: reviewed run, data/formula/code/Dify version records, graph snapshot and audit history.
- Produces: Appendix D, Appendix E, graph snapshot, run chain, checksums and clear scope/limitation declaration.

- [ ] Write failing tests for omitted source hashes, a run that is not result-reviewed, a missing indicator row and accidental inclusion of secrets/teaching data.
- [ ] Generate every §9.3 artifact: manifest, parameters, catalogue, annual rules, adjustments, Appendix E, supplements/reviews/audit JSONL, formula registry, QA, run comparison, report, script, screenshots and checksums.
- [ ] Make the 10-minute script distinguish the actual maize review plus blocked snapshot from any explicitly labelled teaching replay. Do not display a full GEP card until all 22 applicability and input gates pass.
- [ ] Execute two consecutive demonstration rehearsals, including failed supplement and returned review scenarios; record measured response/recalculation timing.
- [ ] Commit `feat: export auditable GEP delivery package`.

### Task 10: Perform full acceptance, independent replay and handover

**Files:**
- Create: `docs/acceptance/2024-haidian-gep-acceptance.md`, `docs/acceptance/host-survey.md`, `docs/acceptance/recovery-log.md`

**Interfaces:**
- Consumes: frozen delivery package and clean restore environment.
- Produces: signed acceptance matrix and deployment handover with remaining gap ownership.

- [ ] Re-run data admission, 22-item applicability, spatial coverage, formula/manual, unit/year/negative/blank, total-ledger, event/review/conflict and local invalidation tests against the frozen inputs.
- [ ] Restore backup into a fresh runtime location, reproduce the same run, compare numerical artifacts at relative error `<=1e-6`, and retain restore logs.
- [ ] Demonstrate that a price correction changes only its descendants; demonstrate that a boundary revision invalidates the spatial chain; record run parentage and cache reuse.
- [ ] Check all host health endpoints, access controls, internal Dify tool connectivity, logs, backup location and rollback command. Record actual ports/routes and image/code/data/formula/workflow versions.
- [ ] Mark the final release only when every applicable indicator is calculated or approved as non-applicable/verified zero, Appendix D/E reconcile, two rehearsals pass and remaining limitations are documented. Commit `docs: record full GEP acceptance evidence`.

## Required Decision Before Task 8

The source scheme plans `8000` for API and `8080` for Web, but says actual ports depend on host configuration. The host currently has active services on both and `/srv` needs sudo. Choose one approved deployment arrangement:

1. Give a reverse-proxy route (for example an existing HTTPS virtual host/path) plus the proxy’s identity-header contract; keep API private.
2. Authorize a specific unused Web/API port pair and whether it is loopback-only or proxied.
3. Authorize a root-owned `/srv/haidian-gep` setup through a working sudo path, or approve `/data/wwj/haidian-gep` as the persistent deployment root.

No architecture, accounting or data-scope choice is implicit in this infrastructure decision. Dify also remains blocked until a real model gateway, credentials mechanism and official pinned Compose version are supplied.

## Completion Evidence

The implementation is complete only with: a validated 2024 boundary/AlphaEarth base; audited inputs and method cards for all 22 indicators; reviewed deterministic results and adjustment ledger; replayable evidence package; an accessible, authenticated host deployment that coexists with existing services; and the §11 measurable acceptance records. The current branch is only the first “real maize evidence → review → formal snapshot blocked by missing price/cost and other inputs” milestone.
