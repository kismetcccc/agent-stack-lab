# ADR 002：MySQL权威状态、Outbox/Inbox、至少一次交付

状态：首轮采纳。

决定：task与outbox同一SQL事务；relay确认发布后标记；consumer把Inbox和ready同事务提交后才提交offset。长任务由SQL租约和fence控制；MongoDB先写结果，再条件更新SQL成功引用；Redis只做可失效提示。

收益：请求提交与待发事件不脱节；消费者ack后任务仍能恢复；旧执行器不能覆盖当前结果；Redis故障不破坏正确性。

代价：需要恢复扫描、事件去重、状态约束、孤儿清理和运维可见性；结果跨库不是原子提交；外部模型可能重复调用。首轮尚未完成跨attempt文档复用和孤儿清理，必须诚实标注。

不采纳：API直接发Kafka然后写SQL；消费者先ack再存任务；只靠Redis锁；把Kafka producer幂等叫作端到端exactly-once。

官方依据：[Kafka交付语义](https://kafka.apache.org/41/design/design/)、[MySQL锁定读取](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html)。
