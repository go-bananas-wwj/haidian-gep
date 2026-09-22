# 海淀 GEP Demo 宿主机部署记录（2026-09-22）

## 已部署范围

- 宿主机部署根：`/data/wwj/haidian-gep`。
- 应用提交：`8b8bc42`（分支 `feature/haidian-gep-demo-core`）。
- 服务：`task-api`（仅 Compose 内网）与 `task-web`（`127.0.0.1:9088`）。
- API 容器镜像 ID：`sha256:fa115a49b560221fb1ed9716c61d9ce903d85ebd299f715b6083ffe2df6c5d73`。
- 持久化卷：`runtime/` 挂载为读写；准入数据目录 `data/` 挂载到 API 的 `/var/lib/haidian-gep-data`，并由 Docker 检查为 `RW=false`。
- 参考数据归档 SHA-256：`9793afbdeeed1a7b11195c68ead6e860ff9a03451492c262f1b299e5419bfe28`。

## 已执行验证

1. `docker compose config` 成功渲染，未发布 API 的宿主机端口；Web 唯一发布项为回环 `9088`。
2. `docker compose up -d --force-recreate --wait --wait-timeout 60` 成功；API 达到 `healthy` 后 Web 才启动。
3. `GET http://127.0.0.1:9088/api/health` 返回 `{"status": "ok"}`；Web 首页可读取。
4. 通过 Web 代理创建 2024 海淀任务，返回 22 个指标节点；玉米来源节点为 `2935.1 t/a`、年鉴来源、`pending_review`。
5. 该任务创建正式快照返回 HTTP `422`，共 24 个阻断项。该行为符合“数据未审核、价格/成本及其他科目输入缺失时不得产生正式 GEP”的准入规则。

## 运行和访问

宿主机本地访问：`http://127.0.0.1:9088`。

远程管理者可用 SSH 本地转发访问，而不将服务暴露到公网：

```bash
ssh -L 9088:127.0.0.1:9088 -p 3751 wwj@218.84.111.20
```

然后在本机打开 `http://127.0.0.1:9088`。是否配置反向代理、身份验证和 TLS 仍需主机管理员明确批准。

## 当前限制

此实例是可运行的“真实年鉴玉米来源节点 → 审核前阻断正式快照”里程碑，不是 2024 全口径正式 GEP 发布。行政边界尚待确认，完整 AlphaEarth 年度资产、价格/成本、水文污染和文化调查等输入尚未完成准入；Dify 亦未配置真实模型工作流和密钥。因此服务不会生成或展示虚构的 22 科目总值。
