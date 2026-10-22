# 当前后端开发环境

本轮默认仅运行 API、Worker、一次性迁移与 MySQL / Kafka / MongoDB / Redis。
可选前端与同源网关已通过独立验收，使用 `compose.ui.yaml` 显式启用，不是后端独立测试的依赖。Kubernetes 与外围可观测性草稿仍未做运行验收。

```bash
python scripts/infra-init-env.py
docker compose up -d --build --wait --wait-timeout 300
# API 与 OpenAPI： http://localhost:8080/docs
bash scripts/test-integration.sh
# 保留数据的停止
docker compose down
```

初始化脚本用密码学随机数生成 URI-safe 密码，默认遇到已有 `.env` 拒绝覆盖。Linux 本地文件系统支持显式 `--fill-missing`，只补缺失/明确空值并保留其他内容；原生 Windows 仅保留排他新建，不能把 POSIX `0600` 当作 NTFS ACL 保证。平台、已有卷与并发限制见 [配置说明](../docs/CONFIGURATION.md)。
MySQL/MongoDB/Redis 有认证；数据库与 Kafka 不发布宿主端口。
Kafka 为单节点 KRaft 开发实例，网络内明文无认证；不是生产安全或高可用配置。
API 仅绑定 `127.0.0.1:8080`。没有公开部署或云资源购买；默认 Compose 不调用真实模型。独立 provider 连通性检查不属于 Compose live 验收。
容器运行 deterministic 模型适配器，绝不能把它描述成真实模型服务。

## 数据与迁移

MySQL 使用 `agentlab` 数据库，账户 `lab`。其余凭据由环境生成。
迁移使用 `python -m backend.migrate`，迁移成功后才启动 API/Worker。
四种数据服务使用独立 named volume。普通停止不删除数据。

**破坏性重置**：`docker compose down --volumes` 会永久删除本项目所有数据库和消息数据。
不要在普通停止、故障演练或有需要保留数据的环境中使用。
更改 `.env` 不会自动更改已初始化数据库密码；重置密码必须分别执行对应数据库操作。

## 测试与证据边界

提交 `102491d2` 的 [CI 39731470818](https://github.com/kismetcccc/agent-stack-lab/actions/runs/39731470818) 已完成真实 Compose 组件、故障恢复与可选 UI 浏览器验证。以下“编写环境未运行容器”不否定独立 CI 的实际证据，也不意味着 Windows 或 Kubernetes 已通过。

- 已运行：官方 Docker Compose v2.35.1 CLI 的 `config --quiet`（离线）；YAML与隔离/迁移依赖不变量验证；脚本语法检查。
- 当前编写环境缺少 Docker daemon，未运行容器；CPU/内存/磁盘占用与启动时间未实测，不给虚构的最低资源承诺。
- 自动 CI 在独立 Ubuntu runner 运行后端静态/单元测试及真实四存储的完整集成、故障恢复测试。
- `artifacts/` 和 `test-results/` 为 CI 证据；实际完成以对应 commit 的 Actions 状态和报告为准。配置文件存在不代表运行成功。
- `scripts/infra-validate.py` 是结构检查，不代替镜像拉取、数据库兼容性或网络/运行时验证。

需要资源数据时，在真实运行环境采集：

```bash
docker compose ps
docker stats --no-stream
docker system df
```

统计启动耗时应从干净环境记录镜像下载与容器启动两段，不能把缓存镜像的结果冒充首次启动结果。

## 镜像来源与锁定

默认镜像版本：`mysql:8.4.7`、`apache/kafka:4.0.0`、`mongo:8.0.6`、`redis:7.4.2`；
应用构建使用 `python:3.12.10-slim-bookworm` 与 `uv==0.13.4`，依赖由根 `uv.lock` 固定。
这些版本用于复现实验，不声明它们是最新版本、无已知漏洞或生产安全基线。
镜像 tag 固定不是 digest 不可变；部署生产前须重做支持期/漏洞评估并锁定已验证 digest。
CI 的实际拉取/运行仍是可用性最终证据，网络或 registry 错误不应被视为测试通过。

官方参考：
- [MySQL 官方镜像 tags](https://hub.docker.com/_/mysql/tags?name=8.4.7)
- [Kafka 4.0 Docker 指引](https://kafka.apache.org/40/getting-started/docker/)
- [Kafka 4.0.0 官方 Dockerfile](https://github.com/apache/kafka/blob/4.0.0/docker/jvm/Dockerfile)：数据卷使用预先赋予 appuser 权限的 `/var/lib/kafka/data`，避免把 root 所有的新卷挂到 `/tmp` 导致无法写入。
- [MongoDB 官方镜像](https://hub.docker.com/_/mongo)
- [Redis 官方镜像](https://hub.docker.com/_/redis)
- [Python 官方镜像](https://hub.docker.com/_/python)
- [Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)

这些来源验证组件/版本来源与配置依据；未完成的镜像 registry HEAD 核验不能替代真实 CI 拉取。
