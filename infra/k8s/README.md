# Kubernetes 教学部署（开发环境）

这里是 **单节点、单副本、非生产** 的 Kubernetes 教学清单草稿。**当前仅有静态检查，尚未执行真实集群验收；默认 CI 没有 Kind job。** 不要把清单存在、Compose 通过或下面的预期流程当作集群已运行的证据。

## 执行

需要 Docker daemon、`kind`（建议 `v0.27.0`）、`kubectl`、Python。仓库根目录执行：

```bash
bash scripts/infra-kind.sh
# 调试时重新开启本地入口（脚本完成后会关闭其临时转发）：
kubectl --context kind-agent-stack-lab -n agent-stack-lab port-forward --address=127.0.0.1 svc/gateway 8080:8080
```

脚本显式绑定 `kind-agent-stack-lab` context，不使用用户当前 context；可用 `KIND_CLUSTER_NAME` 改独立开发集群名。不会公开公网端口，不部署 LoadBalancer/公网 Ingress。

脚本设计的预期顺序（尚未实跑验证）：创建 Kind → 随机生成 Secret（已存在则沿用）→ 构建并加载 API/前端镜像 → 启动四个真实数据服务 → 等待 readiness → 运行迁移 Job → 部署 API/Worker/Nginx → 本地端口转发检查网页、存活与真实依赖就绪接口 → 真实 HTTP 注册、CSRF、幂等提交、轮询任务成功、结果和步骤验收。

- MySQL、MongoDB、Redis、Kafka 都有 PVC。Kind 默认本地存储不等于备份或高可用；删除 Kind 集群会销毁集群数据。
- MySQL 以独立 `lab` 应用账户访问。MongoDB 此教学部署使用私有随机 root 凭据；生产须改为最小权限应用账户。
- Secret 不写入仓库；生成临时文件权限为 `0600` 并立即删除。不通过命令行参数传入实际密码。Kubernetes Secret 默认只是编码而不是加密；真实环境须开启静态加密及外部密钥管理。
- Kafka 的 cluster ID 是公开的非秘密拓扑标识。单节点 KRaft，数据只在集群内部提供，PLAINTEXT **不能用于不可信网络**。
- API `/healthz` 不依赖外部服务；`/readyz` 检查关键服务。Worker 通过心跳命令探针。所有主要容器有限制和请求资源；这些是调度配置，不是实测最低硬件承诺。
- 迁移是单独 Job，不在每个 API 实例启动时无条件建表。重跑脚本会替换 Job，迁移本身需幂等。
- `05-network-policies.yaml` 限制数据服务和 API 的 ingress。**Kind 默认 CNI 不保证执行 NetworkPolicy**；此 smoke 不宣称网络隔离已经验收。要验收隔离须安装支持策略的 CNI 并增加允许/拒绝访问测试。只有 gateway 是浏览器入口。
- `artifacts/kind/` 是本次证据与失败诊断输出；禁止提交或上传 Secret、完整环境快照、真实用户信息。成功日志只证明实际执行过的检查。

## 停止与破坏性重置

普通关闭端口转发不会删除数据。完整删除 **不可恢复地销毁该 Kind 集群及 PVC 数据**：

```bash
kind delete cluster --name agent-stack-lab
```

不要只轮换 Secret 而保留未同步更新凭据的已初始化数据库卷。

## 验收边界

云端开发容器没有 Docker/kubectl 时只能执行 YAML/脚本静态检查；当前没有 GitHub Actions Kind job 或真实集群运行证据。未来启用时须另行记录执行提交、集群版本和通过/失败结果，不以静态检查代替运行成功。本脚本默认使用 deterministic 模型，不产生真实模型调用费用；业务链路、故障恢复与真实模型验收另见项目测试文档。

官方依据：[Kind v0.27.0](https://github.com/kubernetes-sigs/kind/releases/tag/v0.27.0)、[Kind 配置](https://kind.sigs.k8s.io/docs/user/configuration/)、[Kubernetes NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)。
