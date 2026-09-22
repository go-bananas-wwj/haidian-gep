# 部署前置与运行说明

此目录只提供海淀 GEP 任务服务的容器编排；未包含 Dify 镜像、模型密钥、原始数据或教学数值。

## 主机准入

在宿主机认证恢复后，先只读核查 Docker/Compose、8000/8080、反向代理和 `/srv/haidian-gep` 是否空闲。仅当不存在冲突时，才将本仓库置于 `/srv/haidian-gep/app`，并将 `runtime/` 放在持久卷 `/srv/haidian-gep/runtime`。数据库、审核日志和运行产物必须一起备份。

```bash
cd /srv/haidian-gep/app/deploy
docker compose -f compose.demo.yml up -d --build
curl --fail http://127.0.0.1:8000/health
```

API 为 `127.0.0.1:8000`，画布为 `127.0.0.1:8080`。在反向代理、访问控制和 TLS 经过主机核查前，不得将任一端口公开到互联网。

## Dify

按详细方案 §12.1 下载并冻结 Dify 官方、完整 Docker Compose 配置及镜像摘要，独立部署在内部网络。配置真实模型后，业务服务才可调用其工作流。未配置时，本服务会将补充请求保留为 `blocked`，绝不生成模拟候选或“已补充”状态。

## 恢复

停止服务：`docker compose -f compose.demo.yml down`。恢复时先还原 `runtime/` 备份，再验证证据哈希、健康接口和同一 SQLite 数据库中的任务/审核/事件记录。
