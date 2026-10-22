# ADR 001：模块化单体，而不是先拆微服务

状态：首轮采纳。

背景：学习者需要看清一条任务主线，同时接触多种后端组件。多语言多服务会让部署问题盖过领域问题。

决定：Python/FastAPI模块化后端，API与Worker两个入口共享领域、契约和适配器；React/TypeScript前端。Java/Spring Boot只作为未来对照实验。relay/consumer/executor/recovery首先是Worker内部模块。

收益：能在单仓库追踪事务、事件和状态机，复用测试，减少无谓网络调用。

代价：共享发布边界；Worker内部阻塞或故障可能影响多个职责；首轮单relay不能随意扩容。只有观察到独立扩缩容/故障隔离需要，再讨论拆进程或服务。

不采纳：按MySQL/MongoDB/Redis拆服务；同时实现Python和Java主链路；为教学清单同时引入Kafka与RabbitMQ。
