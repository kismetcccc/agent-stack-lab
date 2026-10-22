import { useState, type ReactNode } from "react";
import { BookOpen } from "lucide-react";
import { playgrounds } from "./PlaygroundHome";
import type { LabProps } from "./lab";
import RecordsLab from "./RecordsLab";
import RedisLab from "./RedisLab";
import KafkaLab from "./KafkaLab";
import ConsoleDrawer from "./ConsoleDrawer";

const help: Record<
  string,
  { limits: string; exercise: string; boundary: string }
> = {
  mysql: {
    limits: "名称最多 80 字，内容最多 1000 字；服务端分页每页 10 条。",
    exercise: "新建记录 → 查看服务端详情 → 编辑并重新读取 → 确认后删除。",
    boundary: "只操作独立教学表，不提供原始 SQL、表结构管理或帐号授权。",
  },
  mongo: {
    limits:
      "根节点必须是 JSON 对象：最多 16 KiB、6 层深度、200 个节点。键名不能含点、NUL 或以 $ 开头；大编号用字符串。",
    exercise: "新建文档 → 查看完整 JSON → 替换文档 → 刷新核对旧字段已移除。",
    boundary:
      "保存修改是完整替换，不是字段合并；JSON 只作为数据，不执行 JavaScript 或查询语言。",
  },
  redis: {
    limits:
      "键名 1–64 位英文字母、数字、下划线或横线；值最多 4096 UTF-8 字节；TTL 为 1–3600 秒。",
    exercise:
      "指定键 → 写入并回读 → 再次读取 TTL → 等待后实际确认不存在 → 重新写入并删除。",
    boundary:
      "仅操作 lab:kv: 教学前缀，不触碰任务缓存、不扫描全库。倒计时是本地估算；键缺失不能区分过期、删除或从未创建。",
  },
  kafka: {
    limits:
      "消息键 1–64 位英文字母、数字、下划线或横线；正文最多 4096 UTF-8 字节。",
    exercise:
      "发送一次 → 保留消息 ID → 分别核对生产确认和消费者回执 → 刷新深链接再次查询。",
    boundary:
      "固定教学 topic，不提供重放或管理命令。每个 ID 只尝试发送一次；结果不明先查询，不自动重发。历史回执不代表 broker 当前仍保留消息。",
  },
};

export default function ComponentPlayground({
  component,
  authenticated,
  authPanel,
  mode,
  ...props
}: LabProps & {
  component: string;
  authenticated: boolean;
  authPanel: ReactNode;
  mode?: string;
}) {
  const spec = playgrounds.find((item) => item.id === component)!;
  const [helpOpen, setHelpOpen] = useState(false);
  const modeLabel =
    mode === "production" ? "真实适配器" : mode ? "测试替身" : "模式未确认";
  const modeDescription =
    mode === "production"
      ? "production 仅表示真实组件适配器模式，不代表组件当前正常。"
      : mode
        ? `当前 ${mode}：使用离线 / 测试替身，不代表真实组件集成。`
        : "尚未取得后端模式，不能据此认定为真实组件验收。";
  return (
    <section
      className="component-playground"
      data-testid={`component-${component}`}
    >
      <header className="component-title">
        <div>
          <h1>{spec.label}</h1>
          <p>{spec.purpose}</p>
        </div>
        <div className="component-page-tools">
          <span
            className="lab-scope"
            title="本地教学数据不按帐号隔离；不修改原有任务、帐号或模型配置"
          >
            本地共享
          </span>
          <span className="lab-mode-tag" title={modeDescription}>
            {modeLabel}
          </span>
          <button className="lab-button" onClick={() => setHelpOpen(true)}>
            <BookOpen size={15} />
            帮助
          </button>
        </div>
      </header>
      {!authenticated ? (
        <section className="lab-panel composer lab-auth">
          <p className="lab-help">
            请先登录。教学数据不按帐号隔离，登录不改变共享范围。
          </p>
          {authPanel}
        </section>
      ) : component === "mysql" || component === "mongo" ? (
        <RecordsLab kind={component} {...props} />
      ) : component === "redis" ? (
        <RedisLab {...props} />
      ) : (
        <KafkaLab {...props} />
      )}
      <ConsoleDrawer
        open={helpOpen}
        title={`${spec.name} 帮助`}
        onClose={() => setHelpOpen(false)}
      >
        <div className="lab-help-content">
          <h3>用途</h3>
          <p>{spec.purpose} 无需先创建 Agent 任务。</p>
          <h3>字段限制</h3>
          <p>{help[component].limits}</p>
          <h3>最短练习</h3>
          <p>{help[component].exercise}</p>
          <h3>安全边界</h3>
          <p>{help[component].boundary}</p>
          <p>
            本地共享教学数据，不按帐号隔离；既有登录、CSRF 与 Origin
            校验仍保留。
          </p>
          <h3>运行模式</h3>
          <p>{modeDescription}</p>
          <a
            className="lab-button"
            href={`#architecture-${component}`}
            onClick={() => setHelpOpen(false)}
          >
            查看架构中的职责
          </a>
        </div>
      </ConsoleDrawer>
    </section>
  );
}
