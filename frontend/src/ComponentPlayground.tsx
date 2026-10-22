import type { ReactNode } from "react";
import { ArrowLeft, BookOpen } from "lucide-react";
import { playgrounds } from "./PlaygroundHome";
import type { LabProps } from "./lab";
import RecordsLab from "./RecordsLab";
import RedisLab from "./RedisLab";
import KafkaLab from "./KafkaLab";

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
  return (
    <section
      className="component-playground"
      data-testid={`component-${component}`}
    >
      <div className="component-topline">
        <a href="#playground">
          <ArrowLeft size={14} />
          全部组件
        </a>
        <a href={`#architecture-${component}`}>
          <BookOpen size={14} />
          架构中的职责
        </a>
      </div>
      <div className="component-title">
        <div>
          <span className="intro-kicker">{spec.name} · 独立实验</span>
          <h1>{spec.label}</h1>
          <p>{spec.purpose} 无需先创建任务。</p>
        </div>
        <spec.icon size={28} />
      </div>
      <p className="lab-scope">
        本地共享教学数据 · 不按帐号隔离 · 不修改原有任务、帐号或模型配置
      </p>
      {mode !== "production" && (
        <div className="lab-mode-warning">
          {mode
            ? `当前为 ${mode} 模式：使用离线 / 测试替身，不代表四组件真实集成。`
            : "后端运行模式尚未确认：以下响应不能据此认定为真实组件验收。"}
        </div>
      )}
      {!authenticated ? (
        <section className="lab-panel composer lab-auth">
          <p className="lab-help">
            先使用现有帐号登录，即可直接操作这个组件。登录不意味着实验数据属于个人私有空间。
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
    </section>
  );
}
