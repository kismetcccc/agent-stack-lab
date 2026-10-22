export const components = [
  {
    id: "mysql",
    name: "MySQL",
    label: "事务与事实来源",
    symbol: "SQL",
    tone: "blue",
    description:
      "任务状态、用户权限、幂等键、Outbox / Inbox 与执行租约都在这里。查询任务的最终状态，以关系数据库为准。",
    boundary:
      "不能用消息队列或缓存代替任务状态表。任务与 Outbox 在同一事务提交。",
    experiment:
      "并发提交相同幂等键：数据库唯一约束应让两个请求返回同一任务；同键不同内容必须返回 409。",
  },
  {
    id: "kafka",
    name: "Kafka",
    label: "可靠事件交付",
    symbol: "EVT",
    tone: "violet",
    description:
      "Outbox relay 把持久事件发布到消息队列。Consumer 先将 Inbox 落库，再提交 offset，重复投递不会创建重复工作。",
    boundary:
      "至少一次交付不等于端到端 exactly-once。Kafka 不裁决任务是否成功。",
    experiment:
      "暂停 Kafka 后提交任务：任务留在 pending。恢复后 relay 补发事件，任务继续执行。",
  },
  {
    id: "mongodb",
    name: "MongoDB",
    label: "步骤与结果文档",
    symbol: "DOC",
    tone: "teal",
    description:
      "保存结构灵活的工具输入输出、动作摘要与报告。使用稳定且属于当前 attempt 的文档 ID，避免重复保存。",
    boundary:
      "先写结果文档，再由 MySQL 条件提交结果引用。跨库操作不是一个原子事务。",
    experiment:
      "让文档写入失败：任务不得被标记为成功；恢复后检查重试与最终结果引用。",
  },
  {
    id: "redis",
    name: "Redis",
    label: "可丢弃的加速层",
    symbol: "TTL",
    tone: "amber",
    description:
      "存储有 TTL 的非权威进度或可重建缓存。缓存命中是性能优化，缓存缺失不应该让业务丢失。",
    boundary: "不是任务唯一状态，不是租约恢复的唯一依据；依赖失效时允许降级。",
    experiment:
      "停用或清空 Redis：任务仍应能执行和查询。页面报告实际降级状态，而不是假装在线。",
  },
];
export const chapters = [
  {
    title: "一次提交，两个入口",
    tag: "01 · HTTP 与事务",
    body: "API 负责认证、校验与短事务；Worker 负责耗时执行。两个进程共享领域规则，不需要互相发 HTTP 请求。请求返回 202 只表示已经受理，不代表执行成功。",
  },
  {
    title: "从“双写”到 Outbox",
    tag: "02 · 消息可靠性",
    body: "先写数据库再发消息会留出丢消息窗口，先发消息再写数据库会产生无主消息。任务与 Outbox 同事务提交，将“发消息”变成可重试的持久工作。重复发布由 Inbox 唯一键吸收。",
  },
  {
    title: "进程退出之后，谁来接手？",
    tag: "03 · 租约与恢复",
    body: "执行器领取任务并得到有期限的租约和 fencing token。恢复器重新安排过期任务；旧执行器即便恢复，也不能用旧 token 覆盖新结果。模型调用不能放进数据库长事务。",
  },
  {
    title: "一个成功状态，多个存储",
    tag: "04 · 一致性边界",
    body: "MongoDB 保存文档，MySQL 提交成功及结果引用。中间宕机可能留下孤儿文档，但不能留下指向不存在结果的虚假成功。Redis 可以失效，任务真相仍在 MySQL。",
  },
  {
    title: "观察调用，而非隐藏思维",
    tag: "05 · 可观测性",
    body: "页面显示真实的事件、组件调用与工具动作摘要，使用 task_id、event_id、trace_id 串联。这里不是模型隐藏思维链。deterministic 适配器用于可复现测试，不代表调用了真实模型。",
  },
  {
    title: "部署层不解决业务一致性",
    tag: "06 · Kubernetes",
    body: "Deployment 管理 API / Worker，Service 提供寻址，探针帮助判断存活与就绪，Secret 注入配置。Kubernetes 不在业务请求链路中，也不能替代幂等、Outbox 或数据库事务。部署清单存在不等于已在集群验收。",
  },
];
export const statusNames: Record<string, string> = {
  pending: "等待分发",
  ready: "等待执行",
  running: "执行中",
  retry_wait: "等待重试",
  succeeded: "已完成",
  failed: "失败",
};
