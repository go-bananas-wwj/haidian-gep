# 海淀 GEP Demo 宿主机部署记录（2026-09-22）

## 已部署范围

- 宿主机部署根：`/data/wwj/haidian-gep`。
- 应用提交：`96100be`（API 数据包目录）、`6cd5e7a`（画布准入展示）、`1718a71`（本地视图布局）、`664b094`（按科目展开输入）、`0961252`（事件面板）、`e421062`（AEF 候选状态）、`a3a7eac`（边界准入闸门）、`2c668a0`（待完善附录 E 接口）、`5c7aa4a`（画布展示）及 `d416ab6`（任务中心和图版本迁移），分支 `feature/haidian-gep-demo-core`。
- 服务：`task-api`（仅 Compose 内网）与 `task-web`（`127.0.0.1:9088`）。
- API 容器镜像 ID：`sha256:55c013dc5f32273aacdeee6193c8f52c00fd71952bc5b2ce8333928282f89b79`。
- 持久化卷：`runtime/` 挂载为读写；准入数据目录 `data/` 挂载到 API 的 `/var/lib/haidian-gep-data`，并由 Docker 检查为 `RW=false`。
- 参考数据归档 SHA-256：`9793afbdeeed1a7b11195c68ead6e860ff9a03451492c262f1b299e5419bfe28`。

## 已执行验证

1. `docker compose config` 成功渲染，未发布 API 的宿主机端口；Web 唯一发布项为回环 `9088`。
2. `docker compose up -d --force-recreate --wait --wait-timeout 60` 成功；API 达到 `healthy` 后 Web 才启动。
3. `GET http://127.0.0.1:9088/api/health` 返回 `{"status": "ok"}`；Web 首页可读取。
4. 通过 Web 代理创建 2024 海淀任务，返回 22 个指标节点；玉米来源节点为 `2935.1 t/a`、年鉴来源、`pending_review`。
5. 该任务创建正式快照返回 HTTP `422`，共 24 个阻断项。该行为符合“数据未审核、价格/成本及其他科目输入缺失时不得产生正式 GEP”的准入规则。
6. 部署后在容器内的临时 SQLite 上完成“22 项获审方法/参数版本 → 冻结快照 → 运行”校验：快照记录 22 个公式版本，运行链输入图 SHA-256 长度为 64，运行因“确定性计算引擎尚未配置”保持 `blocked`。该校验不写入持久化运行库。
7. 新任务模板按 22 张方法卡展开 98 个待补输入节点；每张卡含国标附录范围、必填字段、适用性与去重规则。R4 在内陆边界证据通过审核后可以标记为“不适用”，此时不要求海岸计价字段。
8. 临时 SQLite 导出校验返回 22 个公式版本、22 组公式审核记录和 `formal_gep_value: null`；移除 `export_sha256` 后复算 SHA-256 一致。导出校验不写入持久化运行库。
9. 宿主机只读数据卷中的 `reference-2024-v0.1` 发布包可经 `/api/data-versions/reference-2024-v0.1` 读取：清单验证有效，但 `accounting_ready=false`、`full_gep_computed=false`，并返回 22 项缺口。画布在创建任务前展示该准入状态；没有把参考包登记为已准入输入。
10. 画布提供缩放、三类折叠/展开和节点拖拽；布局按任务 ID 存入浏览器本地 `haidian-gep:view-layout:*`，不发送业务写请求、不改变 SQLite 节点、审核、快照或运行记录。
11. 点击任一标准科目会从该任务图中读取同一 `parent_key` 下的必需输入并显示数值、单位、获取状态及审核状态；P1 同时保留玉米年鉴来源节点。其他科目不复用农产品字段或教学值。
12. 画布以 `/tasks/{id}/events?after=<sequence>` 轮询服务端递增事件并显示实际序号、类型、时间与载荷；没有新增事件时不改变图或伪造运行进度。
13. 本地与宿主机均登记了候选台账 `00_catalog/aef_2024_candidate_tiles.json`（SHA-256 `ce44dbb8ff4c57c007af66aacd223ab0307e3ec66d40181f2c788772f3f911de`）。接口显示 3 个候选及 `unconfirmed_osm_demo_boundary`；它们仍为 bbox 候选而非已下载、已裁切或覆盖验收的 AlphaEarth 特征。
14. 容器临时 SQLite 验证完整输入图在未登记边界时被 `boundary_version:b1` 阻断；登记测试边界后冻结图含 64 位几何哈希、面积与 CRS。生产运行库未登记边界，不能把 OSM 演示边界用于正式快照。
15. `GET /api/tasks/{id}/appendix-e` 在容器临时 SQLite 返回 22 行当前任务科目，`formal_gep_value: null`，且 P1 保留阻断状态；该“待完善附录 E”是实时完整性报告，不是快照或正式总值。
16. 宿主机首页实测包含“查看待完善附录 E”操作入口；它只读取任务当前状态并展示 22 科目、输入证据与阻断节点，不创建快照或运行。
17. 升级后通过宿主机 API 读取已有持久化任务：`graph_version=1`、`pending_review_count=1`、`node_blocker_count=23`、无最近运行；首页实测包含任务中心入口。运行库的旧 `tasks` 表已在启动时安全补入默认值为 1 的图版本列。
18. 宿主机运行库已执行 SQLite 在线备份并在新的恢复目录复原；备份文件 SHA-256 验证成功，原库与恢复库均读取到 1 个任务。备份为 `/data/wwj/haidian-gep/backups/runtime-20260922T091048Z`，恢复验证目录为 `/data/wwj/haidian-gep/restore-validation-20260922T091048Z`；准入数据卷没有复制或写入。

## 运行和访问

宿主机本地访问：`http://127.0.0.1:9088`。

远程管理者可用 SSH 本地转发访问，而不将服务暴露到公网：

```bash
ssh -L 9088:127.0.0.1:9088 -p 3751 wwj@218.84.111.20
```

然后在本机打开 `http://127.0.0.1:9088`。是否配置反向代理、身份验证和 TLS 仍需主机管理员明确批准。

## 当前限制

此实例是可运行的“真实年鉴玉米来源节点 → 审核前阻断正式快照”里程碑，不是 2024 全口径正式 GEP 发布。公式版本现在也必须按数据版本记录参数与来源哈希、由受信任身份审核后才能进入快照；生产运行库尚无此类人工批准记录。行政边界尚待确认，完整 AlphaEarth 年度资产、价格/成本、水文污染和文化调查等输入尚未完成准入；Dify 亦未配置真实模型工作流和密钥。因此服务不会生成或展示虚构的 22 科目总值。

部署用受限凭据文件中的 SSH 密码已被宿主机拒绝；本次仅在用户已授权的当前交互认证下完成部署。该受限文件须由凭据所有者轮换或更新，且不得提交、打印或放入镜像。

## 增量部署：Dify 结构化候选契约（2026-09-22）

- 代码提交：`2e5d73a`（`feat: persist reviewed Dify supplement candidates`）。本地 `python3 -m unittest discover -s tests -v` 实测 115 项通过。
- 宿主机使用同一 `deploy` Compose 项目重建；API 镜像 ID 为 `sha256:3c79176edba254c8a905fd7debac6636585599bf8005b6d3d1f2d6100b4c3a5c`。`task-api` 健康且 `task-web` 在 `127.0.0.1:9088` 运行。
- `GET /api/health` 实测返回 `{"status": "ok"}`。容器内 Dify 适配器实测为 `unconfigured`；未写入演示候选、未改动持久化任务的节点或审核记录。
- 当且仅当宿主机受限环境提供 Dify 地址和应用密钥时，服务才向其工作流提交节点工作单。它只接受带数值、单位、说明、来源 SHA-256、定位、许可、工具运行 ID 与提取片段的 JSON 候选；候选始终落为 `candidate_ready/pending_review`，不会自动进入快照。人工在模型运行期间修正同一节点时，迟到候选以版本冲突回滚，不覆盖人工证据。
- Dify 官方完整 Compose、模型/工作流版本及宿主机内部网络地址尚未提供或冻结，故本记录不把 Dify 标记为已部署或已验证；这仍是全口径 Demo 的外部前置依赖。

## 增量部署：异步补充执行器（2026-09-22）

- 代码提交：`78544dc`（`feat: run supplements through persistent worker queue`）。本地 `python3 -m unittest discover -s tests -v` 实测 122 项通过。
- 宿主机以同一 `deploy` Compose 项目重建。`task-api` 健康、`task-web` 仍仅发布 `127.0.0.1:9088`，并新增无宿主机端口的 `task-worker`；API 镜像 ID 为 `sha256:28a9dd82e30028ca8b3aa8ec23c628eeea1a86e3bb43230aebf61defd043bc60`。
- `GET /api/health` 实测返回 `{"status": "ok"}`。运行库补充作业按状态汇总为空，故本次验证没有向已有演示任务写入候选、审核或运行记录。
- 补充接口现在只持久化 `queued` 作业；唯一 worker 以原子认领将其更新为 `running`，然后记录候选待审、配置阻断、工作流失败或版本过期。超过 5 分钟未完成的作业会回到队列并写入 `supplement.requeued` 事件，避免 worker 中断后永久卡住。
- Dify 在本次部署后仍未配置。没有真实模型工作流、经审核外部来源与人工审核时，worker 只保留缺口或阻断，绝不生成 22 科目总值。

## 增量部署：文化服务确定性方法（2026-09-22）

- 代码提交：`fca6724`（`feat: calculate cultural service methods`）。本地 `python3 -m unittest discover -s tests -v` 实测 127 项通过。
- C1 仅在有 2024 分层客源记录、访问量、旅行时间、机会成本、直接旅行成本和归因比例时，按旅行成本路径计算；C2 要求明确将同一活动时间排他归入 C2，按人时乘小时工资计算；C3 分别按年度酒店间夜和住房服务流量及各自景观溢价计算，不接收房产资产成交额。
- 准入层增加了上述受控单位与 `origin`、`deduplication_choice` 两种结构化字段校验；其他字段仍必须是有限数值。参考数据包没有这些真实文化调查输入，故它们仍是正式核算阻断项。
- 宿主机以同一 `deploy` Compose 项目重建。`task-api` 健康、`task-worker` 运行、`task-web` 继续仅发布 `127.0.0.1:9088`；API 镜像 ID 为 `sha256:a264f54d42ca762809f4ad8d1d3f095805043c7b465613f8b8e71a2f47250bdd`。`GET /api/health` 返回 `{"status": "ok"}`，运行库补充作业按状态汇总为空。

## 增量部署：物质产品 P3--P7 方法（2026-09-22）

- 代码提交：`71c5500`（P3/P4/P7）与 `76c9e72`（P5/P6）。本地 `python3 -m unittest discover -s tests -v` 实测 130 项通过。
- P3、P4、P7 使用 A.2 残值路径：实际获取量乘生产者价格，再扣同一产品边界、经审核的完整非生态 `production_cost`；P5 从本地实际用水中扣除外调水和再生水；P6 只计本地实际产出与实际利用量的较小值，并扣生产成本。空白、错误单位和未审输入仍产生可定位阻断。
- 宿主机重建后 `task-api` 健康、`task-worker` 运行、`task-web` 仅绑定 `127.0.0.1:9088`；API 镜像 ID 为 `sha256:f967821df22dee4695e7904bd70e90191ab076749928cb3e9c0dc64b6fb4af8f`，健康接口返回 `{"status": "ok"}`。
- 当前参考数据包没有真实牧业、水产收获、价格/完整成本、水源路由或实际能源设施台账。本部署只交付这些方法的阻断安全实现，不产生上述科目的正式价值或总 GEP。

## 增量部署：R12 与总账调整执行（2026-09-22）

- 代码提交：`82f6874`（R12 排他授粉计算）和 `bc3c4da`（冻结运行应用调整账）。本地 `python3 -m unittest discover -s tests -v` 实测 133 项通过。
- R12 只在作物数量、虫媒依赖度、同口径价格和已审核 `exclusive_to_r12` 选择全部具备时计算；未决选择保持阻断，避免与 P1 双计。
- 冻结图中的已审核调整账现在解析唯一 ID、来源/重叠类别、金额、入账层级与理由；仅 `total` 层调整自三类毛额扣除一次，`item` 层仅审计可见，运行链记录应用摘要。
- 宿主机重建后 `task-api` 健康、`task-worker` 运行、`task-web` 仅绑定 `127.0.0.1:9088`；API 镜像 ID 为 `sha256:d2de4c6cb8f216e2d9580b315a1eb566f5d8233cb177181a5e2c116deacc3b4b`，健康接口返回 `{"status": "ok"}`。真实调整账尚未入库，因而未对现有演示任务产生任何总值。

## 增量部署：R2 与 R9 调节服务方法（2026-09-22）

- 代码提交：`6f574ab`（R2 土壤保持）和 `848f27d`（R9 水净化）。本地 `python3 -m unittest discover -s tests -v` 实测 137 项通过。
- R2 采用潜在 `RKLS` 减覆盖调整后的 `RKLSc` 路径，输入必须是显式的 RUSLE 因子、面积与元/吨价值；R9 按入境负荷、本地排放、出境负荷与人工处理的年度质量平衡计量，人工处理不再归入生态服务。
- 宿主机重建后 `task-api` 健康、`task-worker` 运行、`task-web` 仅绑定 `127.0.0.1:9088`；API 镜像 ID 为 `sha256:e9d957b89f574e2acaedb494004c632f83d047829fc7672cb1d90540734461fb`，健康接口返回 `{"status": "ok"}`。目前未提供 2024 RUSLE 参数或水质断面/处理台账，故两项仍不能形成真实海淀结果。
