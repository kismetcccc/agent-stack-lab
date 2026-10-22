import { useEffect, useState, type ReactNode } from "react";
import {
  BookOpen,
  Database,
  FileJson2,
  FlaskConical,
  GitBranch,
  House,
  KeyRound,
  Layers,
  Menu,
  Send,
  Terminal,
  ChevronRight,
} from "lucide-react";
import ConsoleDrawer from "./ConsoleDrawer";

export const consoleNavigation = [
  {
    group: "工作空间",
    items: [{ id: "playground", label: "总览", icon: House }],
  },
  {
    group: "数据存储",
    items: [
      { id: "mysql", label: "MySQL 记录", icon: Database },
      { id: "mongo", label: "MongoDB 文档", icon: FileJson2 },
    ],
  },
  {
    group: "缓存",
    items: [{ id: "redis", label: "Redis 键值", icon: KeyRound }],
  },
  { group: "消息", items: [{ id: "kafka", label: "Kafka 消息", icon: Send }] },
  {
    group: "任务",
    items: [{ id: "lab", label: "任务与 Agent", icon: Terminal }],
  },
  {
    group: "学习中心",
    items: [
      { id: "overview", label: "架构说明", icon: GitBranch },
      { id: "learn", label: "学习路径", icon: BookOpen },
      { id: "experiments", label: "故障实验", icon: FlaskConical },
    ],
  },
];
export function consoleRoute(page: string) {
  const architecture =
    page === "api" ||
    page === "worker" ||
    ["api", "worker", "mysql", "mongo", "redis", "kafka"].some(
      (id) => page === `architecture-${id}`,
    );
  const id = architecture ? "overview" : page;
  for (const group of consoleNavigation) {
    const item = group.items.find((entry) => entry.id === id);
    if (item) return { ...item, group: group.group };
  }
  return { id: page, label: "未找到页面", group: "工作空间" };
}
export default function ConsoleShell({
  page,
  account,
  children,
}: {
  page: string;
  account: ReactNode;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const route = consoleRoute(page);
  useEffect(() => {
    setMobileOpen(false);
  }, [page]);
  const links = (
    <nav aria-label="主导航">
      {consoleNavigation.map((group) => (
        <div className="console-nav-group" key={group.group}>
          <h2>{group.group}</h2>
          {group.items.map(({ id, label, icon: Icon }) => (
            <a
              key={id}
              href={`#${id}`}
              aria-current={route.id === id ? "page" : undefined}
              className={route.id === id ? "active" : ""}
              onClick={() => setMobileOpen(false)}
            >
              <Icon size={17} />
              <span>{label}</span>
            </a>
          ))}
        </div>
      ))}
    </nav>
  );
  return (
    <div className="app console-app">
      <aside className="console-sidebar">
        <a className="console-brand" href="#playground">
          <Layers size={23} />
          <span>
            Stack Lab<small>本地控制台</small>
          </span>
        </a>
        {links}
        <p className="console-sidebar-note">共享教学空间 · 非生产平台</p>
      </aside>
      <div className="workspace console-workspace">
        <header className="console-topbar">
          <button
            className="icon-button console-mobile-menu"
            aria-label="打开导航"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
          >
            <Menu size={21} />
          </button>
          <div className="console-breadcrumb">
            <span>{route.group}</span>
            <ChevronRight size={14} />
            <strong>{route.label}</strong>
          </div>
          <div className="account">{account}</div>
        </header>
        <main tabIndex={-1} className="console-main">
          {children}
        </main>
      </div>
      <ConsoleDrawer
        open={mobileOpen}
        title="导航菜单"
        closeLabel="关闭导航"
        onClose={() => setMobileOpen(false)}
      >
        {links}
      </ConsoleDrawer>
    </div>
  );
}
