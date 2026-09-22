# 部署前置与运行说明

此目录只提供海淀 GEP 任务服务的容器编排；未包含 Dify 镜像、模型密钥、原始数据或教学数值。

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

编排文件会先等待 API 的 `/health` 成功，再启动 Web 代理。单服务重建期间可短暂返回 `502`；探测与发布脚本应采用带重试的健康检查，而不是把该启动窗口误判为故障。

## Dify

按详细方案 §12.1 下载并冻结 Dify 官方、完整 Docker Compose 配置及镜像摘要，独立部署在内部网络。配置真实模型后，业务服务才可调用其工作流。未配置时，本服务会将补充请求保留为 `blocked`，绝不生成模拟候选或“已补充”状态。

审核接口默认拒绝请求，直到受信任反向代理完成登录验证、移除外部伪造的用户头，并向 API 注入已验证的身份头。届时设置 `GEP_TRUSTED_PROXY_USER_HEADER=HTTP_X_GEP_ACTOR`；浏览器提交的 `reviewer`、`proposer` 字段不会作为审计身份采用。

每个可适用科目还必须提交带参数清单 SHA-256、来源 SHA-256 和方法卡哈希的公式版本，并通过指定版本审核，才能冻结正式快照。相关接口为 `POST /formula-versions`、`POST /formula-versions/{id}/reviews` 及 `GET /formula-versions/{id}/reviews`。这些记录只负责锁定可审计方法与参数；若确定性计算引擎尚未配置，`POST /runs` 仍会以 `blocked` 状态保留运行请求，不产生 GEP 值。

## 恢复

停止服务：`docker compose -f compose.demo.yml down`。恢复时先还原 `$GEP_RUNTIME_DIR` 备份，再验证证据哈希、健康接口和同一 SQLite 数据库中的任务/审核/事件记录。
