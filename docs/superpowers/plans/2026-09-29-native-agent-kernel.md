# 海淀区 GEP 原生智能体内核实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不部署 Dify 的前提下，为现有海淀区 GEP Demo 增加可搜索互联网、检索知识库、调用核算工具并留下完整证据链的原生智能体。

**Architecture:** 在现有异步 Worker 内增加 `gep.agent` 包，使用受约束的 AgentKernel、统一 ToolRegistry、SQLite FTS5 知识库和证据台账。现有 `SmartDataWorkflow` 保留为本地数据优先路径，AgentWorkflow 只通过登记工具取得事实并调用 DeepSeek 做规划和中文解释；`GEP_AGENT_ENABLED=0` 可立即回退到当前 ResearchWorkflow。

**Tech Stack:** Python 3.11+ 标准库、SQLite/FTS5、`urllib`、`pypdf`、现有 WSGI API、原生 HTML/CSS/JavaScript、Docker Compose、pytest/unittest。

**Spec:** `docs/superpowers/specs/2026-09-29-native-agent-kernel-design.md`

## Global Constraints

- 不部署 Dify、LangChain、独立向量数据库或 Kubernetes。
- DeepSeek 只负责意图理解、检索规划、工具选择和中文说明，不得直接制造事实或修改工具返回的数值。
- 模型不得执行任意 Python、Shell、SQL，不得直接请求未登记 URL。
- 所有数值必须能够追溯到证据项和计算步骤。
- 智能试算与正式核算隔离，自动补充不得越过现有正式审核闸门。
- 默认每节点最多 8 次工具调用、3 轮计划、60 秒；达到预算必须返回已有结果和明确缺口。
- Web 读取只允许 HTTP(S)，拒绝本机、内网、链路本地和云元数据地址，并限制超时、重定向、响应大小和内容类型。
- 前端使用中文名称优先、程序字段放在括号内；不再使用无解释的英文状态。
- 密钥只进入 Worker 环境，禁止写入 Git、SQLite、日志和前端响应。
- 每个任务完成测试后提交并推送 `feature/native-agent-kernel`，形成云端回退点。

## Review Focus

- DNS 首次解析为公网、重定向后解析为内网时，读取器必须阻断且不得发送第二个请求；Task 3 增加重绑定/重定向测试。
- FTS5 不可用或旧数据库缺少新表时，Worker 必须安全迁移或确定性降级；Task 2 增加旧库迁移和 FTS5 故障测试。
- 工具返回网页提示注入文本时，内核只能把它当证据内容，不能把其中指令变成工具调用；Task 1 增加提示注入测试。
- Worker 在同一作业重试时，证据、工具运行和计算步骤不得重复；Task 6 增加幂等重试测试。
- 用户快速切换两个抽屉节点时，较慢的旧响应不得覆盖新节点；Task 7 扩展请求版本竞态测试。

---

### Task 1: 智能体类型、工具注册中心与有界状态机

**Files:**
- Create: `gep/agent/__init__.py`
- Create: `gep/agent/types.py`
- Create: `gep/agent/tools.py`
- Create: `gep/agent/kernel.py`
- Modify: `pyproject.toml:17`
- Test: `tests/test_agent_kernel.py`

**Interfaces:**
- Consumes: 无。
- Produces: `ToolSpec`、`ToolResult`、`AgentAction`、`AgentOutcome`、`AgentBudget`；`ToolRegistry.register(spec, handler)`、`ToolRegistry.call(tool_id, arguments)`；`AgentKernel.run(work_order) -> AgentOutcome`。

- [ ] **Step 1: 写失败测试，锁定注册工具和未知工具拒绝行为**

在 `tests/test_agent_kernel.py` 新增 `test_registry_calls_only_registered_tools` 和 `test_registry_rejects_unknown_tool`，断言登记处理器收到经过 Schema 校验的参数，未知工具不会被调用。

- [ ] **Step 2: 运行注册中心测试并确认失败**

Run: `python -m pytest tests/test_agent_kernel.py -k registry -v`

Expected: FAIL，原因是 `gep.agent.tools` 尚不存在。

- [ ] **Step 3: 实现类型和 ToolRegistry**

在 `types.py` 使用冻结 dataclass 定义上述类型；在 `tools.py` 实现显式登记、重复 ID 拒绝、必需字段/类型校验和统一 `ToolResult` 返回。把 `gep.agent` 加入 `pyproject.toml` 的 setuptools packages。

- [ ] **Step 4: 运行注册中心测试并确认通过**

Run: `python -m pytest tests/test_agent_kernel.py -k registry -v`

Expected: PASS。

- [ ] **Step 5: 写失败测试，锁定 8 次调用、3 轮、60 秒和提示注入边界**

新增 `test_kernel_stops_at_tool_call_budget`、`test_kernel_stops_at_round_budget`、`test_kernel_stops_at_elapsed_budget`、`test_tool_text_cannot_create_an_unplanned_action`。使用注入时钟和脚本化 Planner，断言预算耗尽返回 `budget_exhausted`，网页文本中的“调用 shell”不会产生新动作。

- [ ] **Step 6: 运行内核测试并确认失败**

Run: `python -m pytest tests/test_agent_kernel.py -k kernel -v`

Expected: FAIL，原因是 `AgentKernel` 尚不存在。

- [ ] **Step 7: 实现 AgentKernel 有限状态循环**

实现 `AgentKernel(registry, planner, validator, ledger, budget=AgentBudget(), clock=time.monotonic)`。只有 Planner 返回的结构化 `AgentAction` 可以触发已登记工具；ToolResult 内容只能进入观察列表。完成、人工工作包、无更多动作或预算耗尽都返回结构化 `AgentOutcome`。

- [ ] **Step 8: 运行 Task 1 测试与全套回归**

Run: `python -m pytest tests/test_agent_kernel.py -v && python -m pytest -q`

Expected: 新测试全部通过；现有测试全部通过或保持原有可选空间依赖跳过状态。

- [ ] **Step 9: 提交并推送回退点**

```bash
git add pyproject.toml gep/agent tests/test_agent_kernel.py
git commit -m "feat: add bounded native agent kernel"
git push -u origin feature/native-agent-kernel
```

### Task 2: 证据台账与 SQLite FTS5 知识库

**Files:**
- Create: `gep/agent/store.py`
- Create: `gep/agent/knowledge.py`
- Test: `tests/test_agent_store.py`
- Test: `tests/test_agent_knowledge.py`

**Interfaces:**
- Consumes: Task 1 的 `AgentOutcome`、`ToolResult`。
- Produces: `AgentStore(database_path)`；`start_run`、`record_tool_run`、`record_evidence`、`record_calculation_step`、`record_decision`、`latest_node_detail`；`KnowledgeBase.add_document`、`search(query, filters, limit)`。

- [ ] **Step 1: 写失败测试，定义旧数据库迁移和幂等写入**

新增 `test_existing_task_database_is_migrated_without_data_loss`、`test_same_run_and_evidence_are_idempotent`、`test_different_payload_for_same_identity_is_rejected`。测试从只含现有 `tasks/nodes` 的 SQLite 文件启动。

- [ ] **Step 2: 运行存储测试并确认失败**

Run: `python -m pytest tests/test_agent_store.py -v`

Expected: FAIL，原因是 `AgentStore` 尚不存在。

- [ ] **Step 3: 实现 AgentStore 模式和事务写入**

创建 `agent_runs`、`tool_runs`、`evidence_items`、`calculation_steps`、`agent_decisions`、`knowledge_documents`、`knowledge_chunks` 表和必要索引。稳定 ID 由任务/节点/调用序号或内容哈希生成；重试相同内容返回已有记录，不同内容复用同一 ID 抛出冲突错误。

- [ ] **Step 4: 运行存储测试并确认通过**

Run: `python -m pytest tests/test_agent_store.py -v`

Expected: PASS。

- [ ] **Step 5: 写失败测试，定义知识写入、中文检索、过滤和 FTS5 降级**

新增 `test_search_returns_source_locator_and_hash`、`test_search_filters_region_year_and_review_state`、`test_duplicate_document_is_idempotent`、`test_fts5_unavailable_uses_bounded_like_fallback`。

- [ ] **Step 6: 运行知识库测试并确认失败**

Run: `python -m pytest tests/test_agent_knowledge.py -v`

Expected: FAIL，原因是 `KnowledgeBase` 尚不存在。

- [ ] **Step 7: 实现 KnowledgeBase**

优先建立 `knowledge_chunks_fts` 虚表并用 `MATCH` 检索；构建不支持 FTS5 时，在最多 5000 条审核相关记录内执行转义后的 `LIKE` 回退。返回值必须携带文档 ID、标题、发布者、定位、哈希、适用地区/年度、审核状态和片段。

- [ ] **Step 8: 运行 Task 2 测试与全套回归**

Run: `python -m pytest tests/test_agent_store.py tests/test_agent_knowledge.py -v && python -m pytest -q`

Expected: 全部通过。

- [ ] **Step 9: 提交并推送回退点**

```bash
git add gep/agent/store.py gep/agent/knowledge.py tests/test_agent_store.py tests/test_agent_knowledge.py
git commit -m "feat: add agent evidence ledger and knowledge search"
git push origin feature/native-agent-kernel
```

### Task 3: 安全 Web 搜索、网页读取和 PDF 读取

**Files:**
- Create: `gep/agent/http.py`
- Create: `gep/agent/search.py`
- Create: `gep/agent/readers.py`
- Modify: `pyproject.toml:10-13`
- Test: `tests/test_agent_http.py`
- Test: `tests/test_agent_web_tools.py`

**Interfaces:**
- Consumes: Task 1 的 ToolResult；Task 2 的证据字段约定。
- Produces: `SafeHttpClient.fetch(url, *, accepted_types, max_bytes) -> HttpDocument`；`SearchProvider.search(...) -> list[SearchHit]`；`DuckDuckGoHtmlSearchProvider`、`SearxngSearchProvider`；`WebReader.read(url)`、`PdfReader.read(url, pages=None)`。

- [ ] **Step 1: 写失败测试，锁定 URL/DNS/重定向/大小/类型安全**

在 `tests/test_agent_http.py` 新增公网允许、`localhost`/私网/链路本地/元数据地址拒绝、DNS 重绑定、重定向到私网、超过 5 MiB、超过 3 次重定向、非允许类型测试。网络解析和传输全部注入 fake，测试不访问互联网。

- [ ] **Step 2: 运行 HTTP 测试并确认失败**

Run: `python -m pytest tests/test_agent_http.py -v`

Expected: FAIL，原因是 `SafeHttpClient` 尚不存在。

- [ ] **Step 3: 实现 SafeHttpClient**

仅允许 `http`/`https`；每次请求和每次重定向都解析并校验全部地址；拒绝非全局 IP；流式读取且默认最大 5 MiB、超时 10 秒、最多 3 次重定向；错误消息不得包含授权头。

- [ ] **Step 4: 运行 HTTP 测试并确认通过**

Run: `python -m pytest tests/test_agent_http.py -v`

Expected: PASS。

- [ ] **Step 5: 写失败测试，定义搜索归一化和原文读取**

在 `tests/test_agent_web_tools.py` 新增 DuckDuckGo HTML、SearXNG JSON、HTML 正文与元数据、PDF 指定页、搜索结果不直接成为证据、页面中的提示注入保持纯文本等测试。

- [ ] **Step 6: 运行 Web 工具测试并确认失败**

Run: `python -m pytest tests/test_agent_web_tools.py -v`

Expected: FAIL，原因是搜索器和读取器尚不存在。

- [ ] **Step 7: 实现搜索器与读取器**

使用标准库解析 HTML；新增 `pypdf>=5,<6` 仅用于 PDF 文本提取。DuckDuckGo 作为无密钥发现适配器，SearXNG 由 `GEP_SEARXNG_URL` 配置。所有 SearchHit 标记 `discovery_only=True`，只有读取原页面后才生成可校验证据。

- [ ] **Step 8: 运行 Task 3 测试与全套回归**

Run: `python -m pytest tests/test_agent_http.py tests/test_agent_web_tools.py -v && python -m pytest -q`

Expected: 全部通过。

- [ ] **Step 9: 提交并推送回退点**

```bash
git add pyproject.toml gep/agent/http.py gep/agent/search.py gep/agent/readers.py tests/test_agent_http.py tests/test_agent_web_tools.py
git commit -m "feat: add safe web search and document readers"
git push origin feature/native-agent-kernel
```

### Task 4: 证据校验器与风险分流

**Files:**
- Create: `gep/agent/evidence.py`
- Test: `tests/test_agent_evidence.py`

**Interfaces:**
- Consumes: Task 2 的知识/证据记录；Task 3 的原文读取结果。
- Produces: `EvidenceValidator.validate(target, items) -> ValidationResult`，其中包含 `accepted_items`、`rejected_items`、`risk_tier`、`conflicts`、`unit_conversions`、`human_action`。

- [ ] **Step 1: 写失败测试，覆盖来源、地区、年度、单位、冲突和新鲜度**

新增 A/B/C/D 四级案例；同口径不同值必须为 D；跨区论文参数为 C；完全匹配准入观测为 A；可复算官方公开数据为 B；价格过期必须降低等级。

- [ ] **Step 2: 运行校验器测试并确认失败**

Run: `python -m pytest tests/test_agent_evidence.py -v`

Expected: FAIL，原因是 `EvidenceValidator` 尚不存在。

- [ ] **Step 3: 实现确定性校验器**

使用明确规则表而非模型判断风险；单位只允许登记的线性转换；缺失定位、哈希或获取时间的网页记录不得进入 accepted；冲突输出一个归并复核事项。

- [ ] **Step 4: 运行 Task 4 测试与全套回归**

Run: `python -m pytest tests/test_agent_evidence.py -v && python -m pytest -q`

Expected: 全部通过。

- [ ] **Step 5: 提交并推送回退点**

```bash
git add gep/agent/evidence.py tests/test_agent_evidence.py
git commit -m "feat: validate and classify agent evidence"
git push origin feature/native-agent-kernel
```

### Task 5: 内置数据/知识/空间/核算工具与 DeepSeek 规划器

**Files:**
- Create: `gep/agent/builtin_tools.py`
- Create: `gep/agent/planner.py`
- Modify: `gep/deepseek.py:9-87`
- Test: `tests/test_agent_builtin_tools.py`
- Test: `tests/test_agent_planner.py`

**Interfaces:**
- Consumes: Task 1 ToolRegistry；Task 2 AgentStore/KnowledgeBase；Task 3 搜索与读取器；Task 4 EvidenceValidator；现有 `EvidenceCatalog`、`SmartDataStore`、`OfficialSourceRegistry`、`AefSpatialTool` 和公式注册表。
- Produces: `register_builtin_tools(registry, context)`；工具 ID 与规格一致；`DeepSeekPlanner.next_action(context) -> AgentAction`；`TemplatePlanner` 作为模型不可用时的确定性回退。

- [ ] **Step 1: 写失败测试，定义十个登记工具的真实适配行为**

验证本地目录、后台观测、官方注册表、知识库、Web 搜索、Web/PDF 读取、AlphaEarth、GEP 方法和证据校验工具只返回结构化结果；核算工具拒绝未知方法和缺少单位的输入。

- [ ] **Step 2: 运行内置工具测试并确认失败**

Run: `python -m pytest tests/test_agent_builtin_tools.py -v`

Expected: FAIL，原因是 `register_builtin_tools` 尚不存在。

- [ ] **Step 3: 实现内置工具适配器**

复用现有组件，不复制公式；每个结果携带工具 ID、执行耗时、警告和证据引用。所有网络访问只能经过 Task 3 的 SafeHttpClient。

- [ ] **Step 4: 运行内置工具测试并确认通过**

Run: `python -m pytest tests/test_agent_builtin_tools.py -v`

Expected: PASS。

- [ ] **Step 5: 写失败测试，定义 DeepSeek JSON 计划和确定性降级**

新增有效动作、未知工具拒绝、字段类型错误重试一次、第二次无效后 TemplatePlanner 接管、解释数字由结构化结果注入且不能被模型改写等测试。

- [ ] **Step 6: 运行规划器测试并确认失败**

Run: `python -m pytest tests/test_agent_planner.py -v`

Expected: FAIL，原因是 `DeepSeekPlanner` 尚不存在。

- [ ] **Step 7: 实现规划器并扩展 DeepSeek 适配器**

为 `DeepSeekWorkflow` 增加通用 `complete_json(system_prompt, payload)`，保留现有 `run` 兼容行为。Planner 只接受 ToolRegistry 提供的工具清单；解释器接收只读结构化结果，所有显示数字在模型返回后由模板替换/注入。

- [ ] **Step 8: 运行 Task 5 测试与全套回归**

Run: `python -m pytest tests/test_agent_builtin_tools.py tests/test_agent_planner.py tests/test_deepseek.py -v && python -m pytest -q`

Expected: 全部通过。

- [ ] **Step 9: 提交并推送回退点**

```bash
git add gep/agent/builtin_tools.py gep/agent/planner.py gep/deepseek.py tests/test_agent_builtin_tools.py tests/test_agent_planner.py tests/test_deepseek.py
git commit -m "feat: connect GEP tools to DeepSeek planner"
git push origin feature/native-agent-kernel
```

### Task 6: AgentWorkflow、Worker 接入与可回退开关

**Files:**
- Create: `gep/agent/workflow.py`
- Modify: `gep/supplement.py:23-51`
- Modify: `gep/worker.py:12-24`
- Modify: `deploy/compose.demo.yml:20-40`
- Test: `tests/test_agent_workflow.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_deepseek.py`
- Test: `tests/test_deploy_config.py`

**Interfaces:**
- Consumes: Tasks 1-5；现有 SupplementWorkflow 的 `run(work_order) -> dict`。
- Produces: `AgentWorkflow.run(work_order) -> dict`；`workflow_from_environment(environment, *, database_path=None)`；环境变量 `GEP_AGENT_ENABLED`、`GEP_SEARCH_PROVIDER`、`GEP_SEARXNG_URL`。

- [ ] **Step 1: 写失败测试，定义功能开关与兼容回退**

验证 `GEP_AGENT_ENABLED=1` 且有数据库路径时选择 AgentWorkflow；为 0 时保持现有 ResearchWorkflow；缺失 DeepSeek 时仍使用 TemplatePlanner；Dify 适配器保留但不默认选择。

- [ ] **Step 2: 运行选择测试并确认失败**

Run: `python -m pytest tests/test_deepseek.py tests/test_worker.py -k 'agent or environment or workflow' -v`

Expected: FAIL，原因是环境选择尚未支持 AgentWorkflow。

- [ ] **Step 3: 实现 AgentWorkflow 和运行时接入**

AgentWorkflow 先执行 `smart.observation.search`，再按 Kernel 计划检索；结果映射为现有 candidate/manual_required 结构。Worker 把 `database_path` 传入工厂；Compose 仅向 Worker 注入新变量，API 和 Web 不获得密钥。

- [ ] **Step 4: 写失败测试，锁定作业重试幂等和模型/搜索故障降级**

新增同一 supplement job 连续处理两次不重复台账、DeepSeek 超时仍复用本地观测、搜索失败返回具体工具错误与下一步、来源冲突生成一个工作包等测试。

- [ ] **Step 5: 运行工作流测试并确认失败**

Run: `python -m pytest tests/test_agent_workflow.py -v`

Expected: FAIL，原因是端到端映射和幂等尚未完成。

- [ ] **Step 6: 完成结果映射和故障降级**

确保 A 自动候选、B/C 智能试算候选、D 归并人工工作包；任何成功工具结果在后续工具失败时仍保留；对外错误和台账均不含密钥。

- [ ] **Step 7: 运行 Task 6 测试与全套回归**

Run: `python -m pytest tests/test_agent_workflow.py tests/test_worker.py tests/test_deepseek.py tests/test_deploy_config.py -v && python -m pytest -q`

Expected: 全部通过。

- [ ] **Step 8: 提交并推送回退点**

```bash
git add gep/agent/workflow.py gep/supplement.py gep/worker.py deploy/compose.demo.yml tests/test_agent_workflow.py tests/test_worker.py tests/test_deepseek.py tests/test_deploy_config.py
git commit -m "feat: run native agent in supplement worker"
git push origin feature/native-agent-kernel
```

### Task 7: 讲题式节点 API 与中文右侧抽屉

**Files:**
- Modify: `gep/task_service.py:80-180` and node detail methods
- Modify: `gep/api.py` route dispatch and response methods
- Modify: `gep/web/api.js`
- Create: `gep/web/labels.js`
- Modify: `gep/web/index.html:67-80`
- Modify: `gep/web/app.js:173-235`
- Modify: `gep/web/styles.css:15-21`
- Test: `tests/test_api.py`
- Test: `tests/test_task_service.py`
- Test: `tests/web/test_task_canvas.py`
- Test: `tests/web/test_guided_browser_ux.py`

**Interfaces:**
- Consumes: Task 2 `AgentStore.latest_node_detail` 和现有 calculation chain。
- Produces: `GET /tasks/{task_id}/nodes/{node_id}/agent-detail`；前端 `taskApi.agentDetail(taskId, nodeId)`；统一中文 `fieldLabel(field)`。

- [ ] **Step 1: 写失败测试，定义节点讲题数据合同**

服务/API 测试断言响应包含 `objective`、`required_inputs`、`method`、`substitution`、`steps`、`result_interpretation`、`sources`、`tool_timeline`、`risks`、`human_actions`，且跨任务节点返回 404。

- [ ] **Step 2: 运行 API 测试并确认失败**

Run: `python -m pytest tests/test_task_service.py tests/test_api.py -k agent_detail -v`

Expected: FAIL，原因是节点讲题接口尚不存在。

- [ ] **Step 3: 实现服务和 API**

从 AgentStore、现有节点证据和 calculation chain 组装只读数据；无 Agent 运行的旧节点返回结构完整的回退说明，不返回 500。

- [ ] **Step 4: 运行 API 测试并确认通过**

Run: `python -m pytest tests/test_task_service.py tests/test_api.py -k agent_detail -v`

Expected: PASS。

- [ ] **Step 5: 写失败浏览器/静态合同测试，定义十段抽屉和中文标签**

新增“核算对象—本步目标—所需输入—计算方法—代入与计算—结果怎么理解—数据来源—执行记录—风险与人工事项—审核操作”顺序断言；`ecosystem_area` 显示为“生态系统面积（ecosystem_area）”；不出现 `pending`、`applicable` 或“智能体如何补充”。扩展快速切换节点的请求版本竞态测试。

- [ ] **Step 6: 运行前端测试并确认失败**

Run: `python -m pytest tests/web/test_task_canvas.py tests/web/test_guided_browser_ux.py -v`

Expected: FAIL，原因是旧抽屉结构仍在。

- [ ] **Step 7: 实现中文讲题式抽屉**

新增 labels 映射和安全 DOM 渲染；来源链接仅允许 `https://`；工具时间线使用可折叠详情；人工区域只显示未解决事项。继续使用 `drawerRequestVersion` 防止旧响应覆盖当前节点。

- [ ] **Step 8: 运行 Task 7 测试与全套回归**

Run: `python -m pytest tests/test_task_service.py tests/test_api.py tests/web/test_task_canvas.py tests/web/test_guided_browser_ux.py -v && python -m pytest -q`

Expected: 全部通过。

- [ ] **Step 9: 提交并推送回退点**

```bash
git add gep/task_service.py gep/api.py gep/web/api.js gep/web/labels.js gep/web/index.html gep/web/app.js gep/web/styles.css tests/test_api.py tests/test_task_service.py tests/web/test_task_canvas.py tests/web/test_guided_browser_ux.py
git commit -m "feat: explain GEP calculations in Chinese drawer"
git push origin feature/native-agent-kernel
```

### Task 8: 知识导入、真实验收、合并和 9088 部署

**Files:**
- Create: `scripts/index_knowledge.py`
- Modify: `gep/__main__.py` CLI dispatch
- Modify: `README.md`
- Modify: `deploy/README.md`
- Modify: `docs/validation.md`
- Test: `tests/test_knowledge_cli.py`
- Test: `tests/test_deploy_config.py`
- Test: `tests/web/test_smart_data_ui.py`

**Interfaces:**
- Consumes: Tasks 1-7 完整链路。
- Produces: `haidian-gep index-knowledge --database PATH --data-root PATH`；可重复的知识索引；9088 上线版本和回退 SHA。

- [ ] **Step 1: 写失败测试，定义知识导入的可重复性和来源字段**

测试导入标准/项目文档时必须携带标题、发布者、定位、哈希、访问条件和审核状态；重复执行不增加记录；无法读取的 PDF 记录错误但不破坏已导入文档。

- [ ] **Step 2: 运行 CLI 测试并确认失败**

Run: `python -m pytest tests/test_knowledge_cli.py -v`

Expected: FAIL，原因是 `index-knowledge` 命令尚不存在。

- [ ] **Step 3: 实现导入命令和运维文档**

默认索引项目允许的 Markdown/JSON 和明确指定的 PDF；不递归抓取未知目录；记录文档哈希以支持增量重建。README 说明搜索供应商、功能开关、凭据注入、知识重建和回退步骤。

- [ ] **Step 4: 运行完整自动化验证**

Run: `python -m pytest -q`

Expected: 所有常规测试通过；仅缺少可选空间依赖的测试允许明确跳过。

Run: `python -m pytest tests/test_smart_data_aef.py tests/test_smart_data_assets.py tests/test_smart_data_observations.py -q`

Expected: 在空间测试环境中全部通过。

- [ ] **Step 5: 执行真实数据与浏览器验收**

对 2024 海淀任务运行：一个本地观测自动完成、一个公开 Web 来源完成搜索/读取/校验/知识入库、一个计算节点生成公式与步骤、一个冲突案例进入归并工作包。用 Playwright 检查桌面和移动抽屉、持续水流动画、快速切换节点、整批确认，并保存截图和错误计数。

Expected: 浏览器运行时错误为 0；抽屉显示十段中文讲题信息；数值与台账一致。

- [ ] **Step 6: 更新验证记录并提交最终功能分支回退点**

```bash
git add scripts/index_knowledge.py gep/__main__.py README.md deploy/README.md docs/validation.md tests/test_knowledge_cli.py tests/test_deploy_config.py tests/web/test_smart_data_ui.py
git commit -m "feat: index GEP knowledge and document agent release"
git push origin feature/native-agent-kernel
```

- [ ] **Step 7: 合并主分支、推送并部署**

在全套测试和最终代码审查通过后，将 `feature/native-agent-kernel` 快进合并到 `main`，推送 GitHub；按 `deploy/README.md` 先备份运行库和当前 release，再发布新 SHA。保留上一个 release 目录和 `GEP_AGENT_ENABLED=0` 双重回退方式。

- [ ] **Step 8: 验证线上 9088**

检查 API/Web/Worker 健康状态、任务创建、自动补充、Agent 台账接口、右侧抽屉和整批确认。将上线 SHA、备份位置、回退 SHA、测试计数和验收截图路径写入 `docs/validation.md`，提交并推送最终部署记录。
