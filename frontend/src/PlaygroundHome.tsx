import {
  ArrowRight,
  Database,
  FileJson2,
  KeyRound,
  Send,
  Sparkles,
} from "lucide-react";

export const playgrounds = [
  {
    id: "mysql",
    name: "MySQL",
    label: "记录的增删改查",
    purpose: "保存一条记录，再读取、修改和删除。",
    action: "创建第一条记录",
    icon: Database,
    evidence: "看到数据库中的 ID、内容和更新时间",
  },
  {
    id: "redis",
    name: "Redis",
    label: "键值与自动过期",
    purpose: "写入一个带 TTL 的值，观察它何时消失。",
    action: "写入一个临时值",
    icon: KeyRound,
    evidence: "读取真实值与 TTL，并向服务端确认过期",
  },
  {
    id: "mongo",
    name: "MongoDB",
    label: "灵活的 JSON 文档",
    purpose: "保存不同结构的 JSON，读取并替换文档。",
    action: "保存一份 JSON",
    icon: FileJson2,
    evidence: "看到持久化文档及服务端生成的 ID",
  },
  {
    id: "kafka",
    name: "Kafka",
    label: "发送与消费分开看",
    purpose: "发送一条消息，分别检查生产确认和消费记录。",
    action: "发送一条消息",
    icon: Send,
    evidence: "核对实际收到的内容、分区与 offset",
  },
];

export default function PlaygroundHome() {
  return (
    <section className="playground-home">
      <div className="playground-intro">
        <span className="intro-kicker">
          <Sparkles size={15} /> 直接操作，理解组件
        </span>
        <h1>选一个组件，动手试一次。</h1>
        <p>不必先运行 Agent 任务。输入、点击，再看后端实际保存或返回了什么。</p>
      </div>
      <div className="playground-cards">
        {playgrounds.map(
          ({ id, name, label, purpose, action, evidence, icon: Icon }) => (
            <a className="playground-card" href={`#${id}`} key={id}>
              <div className="playground-card-top">
                <Icon size={22} />
                <span>{name}</span>
              </div>
              <h2>{label}</h2>
              <p>{purpose}</p>
              <small>{evidence}</small>
              <span className="playground-card-action">
                {action}
                <ArrowRight size={16} />
              </span>
            </a>
          ),
        )}
      </div>
      <div className="shared-space-note">
        <strong>你的本地共享教学空间</strong>
        <p>
          保留现有登录，实验数据不按帐号隔离。这里操作独立的教学记录，不会修改原有任务或帐号；请勿写入隐私、密钥或重要资料。
        </p>
      </div>
      <div className="playground-secondary">
        <span>想继续深入？</span>
        <a href="#lab">
          任务与 Agent <ArrowRight size={14} />
        </a>
        <a href="#overview">
          架构说明 <ArrowRight size={14} />
        </a>
        <a href="#learn">
          学习路径 <ArrowRight size={14} />
        </a>
      </div>
    </section>
  );
}
