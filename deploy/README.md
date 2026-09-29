# 部署前置与运行说明

此目录提供海淀 GEP 任务服务与原生智能体的容器编排；不需要 Dify 镜像，也不包含模型密钥、原始数据或教学数值。

## 主机准入

在宿主机认证恢复后，先只读核查 Docker/Compose、8000/8080、反向代理和部署根目录是否空闲。当前经批准的根目录是 `/data/wwj/haidian-gep`；应用、运行时数据库和审核事件分别位于 `app/`、`runtime/`，准入数据位于 `data/`。数据库、审核日志和运行产物必须一起备份。

```bash
cd /data/wwj/haidian-gep/app/deploy
export GEP_RUNTIME_DIR=/data/wwj/haidian-gep/runtime
export GEP_DATA_DIR=/data/wwj/haidian-gep/data
docker compose -f compose.demo.yml up -d --build
curl --fail http://127.0.0.1:9088/api/health
```

API 不绑定宿主机端口，仅位于 Compose 内部网络；画布为 `127.0.0.1:9088`，经 `/api/` 代理访问 API，不会启动第二个 SQLite 写进程。`data/` 以只读方式挂载进 API 容器，容器不能改写准入原件或清洗数据。`9088` 是用户于 2026-09-22 批准的入口；在反向代理、访问控制和 TLS 经过主机核查前，不得将其公开到互联网。

当前 Compose 是回环地址上的单用户 Demo，Nginx 会覆盖外部同名头并注入固定 `X-GEP-Actor: demo-reviewer`，API 只信任该代理头，用于逐项和整批审核审计。正式公开前必须替换为真实登录身份和访问控制，不能沿用固定 Demo 身份。

`task-worker` 是同一 Compose 项目中唯一的研究执行器，不发布宿主机端口。`POST /tasks/{id}/supplement` 只将带幂等键的请求写为 `queued`；worker 从同一 SQLite 运行时卷原子认领为 `running`，依次检查本地准入目录、版本化官方来源注册表和适用的 AEF 空间资产，再写入 A 自动采用、B 建议复核、research-gap、C 专家介入、failed 或 stale。容器或浏览器重启不会抹去已排队任务；已完成 research-gap 不会因恢复页面而循环重跑。候选与人工新版本冲突时作业保留为 `stale`，不覆盖节点。

编排文件会先等待 API 的 `/health` 成功，再启动 Web 代理。单服务重建期间可短暂返回 `502`；探测与发布脚本应采用带重试的健康检查，而不是把该启动窗口误判为故障。

## 原生智能体与工具配置

当前 Demo 使用项目自有 `AgentKernel`，在 `task-worker` 内编排本地数据、SQLite FTS5 知识库、安全 Web 搜索/原文读取、AlphaEarth 和登记 GEP 公式。DeepSeek 直连适配器只负责生成结构化工具计划和不含自造数字的中文说明；Dify 继续作为关闭原生智能体后的可选兼容适配器。只有 `task-worker` 接收模型与搜索配置，API 和 Web 容器不取得密钥。

在宿主机运行目录创建权限为 `0600` 的环境文件，例如 `/data/wwj/haidian-gep/runtime/deepseek.env`。通过不回显的交互输入写入 `DEEPSEEK_API_KEY`，并设置：

```text
SUPPLEMENT_PROVIDER=deepseek
GEP_AGENT_ENABLED=1
GEP_SEARCH_PROVIDER=duckduckgo
DEEPSEEK_API_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT_SECONDS=30
```

密钥不得出现在 shell 历史、Compose 文件、Git、镜像层、SQLite、事件、静态资源、截图或导出包中。启动前只核验变量是否存在和文件权限，不打印变量值；部署后以仅报告文件名/计数的扫描方式检查容器配置、应用日志、运行数据库和静态资源。DeepSeek 不能决定数值、来源和风险等级。A 限于完全匹配的准入事实；B 为官方公开值或确定性公开数据计算；C 为代理、论文参数或模型估算，只进入智能试算；D 为冲突、授权或业务口径，归并成人工工作包。

如部署内部 SearXNG，设置 `GEP_SEARCH_PROVIDER=searxng` 与 `GEP_SEARXNG_URL`；否则使用 DuckDuckGo 发现适配器。搜索结果必须继续经过 `web.read`/`document.read`，不能直接作为证据。启动服务前可重建知识索引：

```bash
python -m gep index-knowledge \
  --database /data/wwj/haidian-gep/runtime/tasks.sqlite3 \
  --data-root /data/wwj/haidian-gep/data
```

## 官方来源、AEF 与批量审核

`gep/official_sources.json` 是随代码版本冻结的政府来源注册表。worker 只接受 allowlist 中的北京市政府 HTTPS 域名，在线验证最终 URL 后再使用登记事实；越界重定向、网络失败或口径不一致均不能自动采用。首批登记包括北京市园林绿化局 2024 年绿化资源、公园名录，北京市水务局 2024 年水资源公报及北京市生态环境状况公报。

AEF 工具只检查 2024 VRT、64 波段、10 m、EPSG:32650、Source Cooperative COG、正式边界、训练标签和验证产物。只有输出栅格哈希与验证记录一致时才返回 ready；当前仅有 VRT/索引时必须返回 research-gap，不得声称已经完成绿地分类。

`GET /tasks/{id}/batch-review-preview` 展示 A、B、research-gap、C、失败和硬阻断；`POST /tasks/{id}/batch-reviews` 在可信代理身份下批量批准当前版本的 A/B 节点。取消整批确认不修改数据并返回逐项队列。research-gap、C、失败和版本冲突不能被批量确认绕过。

启动时在受限会话中加载该文件，再运行 Compose：

```bash
set -a
. /data/wwj/haidian-gep/runtime/deepseek.env
set +a
GEP_RUNTIME_DIR=/data/wwj/haidian-gep/runtime GEP_DATA_DIR=/data/wwj/haidian-gep/data \
  docker compose -f compose.demo.yml up -d --build
curl --fail http://127.0.0.1:9088/api/health
```

升级前运行 `backup.sh` 备份 SQLite、审核事件和运行产物，将新代码解压到独立 release 目录后再重建服务。健康检查、任务恢复、worker 队列和浏览器验收任一失败时，切回前一 release 目录并还原对应运行时备份。

### 可选 Dify 编排

按详细方案 §12.1 下载并冻结 Dify 官方、完整 Docker Compose 配置及镜像摘要，独立部署在内部网络。配置真实模型后，业务服务才可调用其工作流。未配置时，本服务会将补充请求保留为 `blocked`，绝不生成模拟候选或“已补充”状态。

将 Dify 地址和应用密钥仅写入宿主机由 `wwj` 限制读取的环境文件（例如 `/data/wwj/haidian-gep/runtime/dify.env`），并在启动前由受限会话导入；不得把该文件、密钥、模型返回的完整请求头或模型提示词提交到 Git、镜像层、SQLite 事件或导出包。工作流必须接受 `work_order_json`，并返回名为 `candidate_json` 的 JSON 对象，含 `value`、`unit`、`explanation` 及带来源 SHA-256、定位、许可、工具运行 ID 与提取片段的 `evidence`。服务只将通过该结构校验的结果写为 `candidate_ready/pending_review`；审核通过前不进入快照。

审核接口默认拒绝请求，直到受信任反向代理完成登录验证、移除外部伪造的用户头，并向 API 注入已验证的身份头。届时设置 `GEP_TRUSTED_PROXY_USER_HEADER=HTTP_X_GEP_ACTOR`；浏览器提交的 `reviewer`、`proposer` 字段不会作为审计身份采用。

每个可适用科目还必须提交带参数清单 SHA-256、来源 SHA-256 和方法卡哈希的公式版本，并通过指定版本审核，才能冻结正式快照。相关接口为 `POST /formula-versions`、`POST /formula-versions/{id}/reviews` 及 `GET /formula-versions/{id}/reviews`。`GET /snapshots/{id}/export` 返回自带 SHA-256 的冻结审计包，其中 GEP 值明确为 `null`，可供下载端独立验签。这些记录只负责锁定可审计方法与参数；若确定性计算引擎尚未配置，`POST /runs` 仍会以 `blocked` 状态保留运行请求，不产生 GEP 值。

## 恢复

停止服务：`docker compose -f compose.demo.yml down`。恢复时先还原 `$GEP_RUNTIME_DIR` 备份，再验证证据哈希、健康接口和同一 SQLite 数据库中的任务/审核/事件记录。

### 智能数据版本回退

`smart-data-2024-v1` 启用数据资产后台、模型估算和智能试算；大型 AEF、MODIS、DEM、WorldCover 产物仍位于只读 `$GEP_DATA_DIR`，不会写入镜像。API 与 worker 必须同时设置 `GEP_SMART_DATA_ENABLED=1`，Web 和 API 不接收模型密钥。

若智能数据流程异常，先设置 `GEP_SMART_DATA_ENABLED=0` 并重建容器，恢复旧研究流程；若数据库、页面或运行恢复仍不通过，则切换到上一 release 的 Compose 文件并还原该 release 对应的运行时备份。关闭功能开关不会删除智能数据表、资产或计算链。

### 原生智能体回退

若 Web 搜索、知识检索或 Agent 规划出现异常，先设置 `GEP_AGENT_ENABLED=0` 并重建 `task-worker`，恢复现有 `SmartDataWorkflow + ResearchWorkflow`；该操作不删除 `agent_runs`、`tool_runs`、`evidence_items`、`calculation_steps`、`agent_decisions` 或知识表。若旧流程也不能恢复，再切回上一 release 并还原对应运行时备份。
