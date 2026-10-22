# 前端验收：真实状态与清晰的组件边界

## 范围

2026-10-22 用户恢复前端任务：参考 Codex 式简洁、浅色侧栏工作区，让组件职责清楚可见。Kubernetes不在本轮范围。前端不能把设计图当实时健康图，也不能以倒计时或静态假结果代替实际执行。

两层证据分开记录：

1. **匿名视觉/交互检查**：可以在本地 Vite 页面执行；没有后端时必须如实呈现未知/不可用，不能宣称完整链路成功。
2. **真实业务浏览器验收**：必须启动 Compose 的 MySQL、Kafka、MongoDB、Redis、API、Worker，以及 UI gateway；仅模型为 deterministic。验收开始检查真实 readyz 的 production 模式和依赖状态，不能用 mock API 或 demo adapter 通过。

## 命令与安全

```bash
# 基础设施负责人提供 compose.ui.yaml，API内部8000、网关localhost8081
# 启动真实服务后：
TEST_BASE_URL=http://localhost:8081 bash scripts/test-e2e.sh
```

APP_ORIGIN 必须与浏览器完全一致：`http://localhost:8081`。不使用127.0.0.1替代Origin，不允许宽泛CORS来掩盖配置问题。

- Playwright固定版本1.62.1（Chromium151.0.7922.34）；npm缓存 `/tmp/agent-stack-npm-cache`；浏览器 `/tmp/agent-stack-playwright`。
- Chromium sandbox开启；不通过禁用沙箱绕过权限错误。
- trace/video关闭，避免会话Cookie或CSRF进入artifact；不写storageState。
- 仅临时教学帐号和公开测试主题；截图不包含密码输入或敏感内容。
- 允许上传 `test-results/browser.xml` 与 `test-results/browser-artifacts/**/*.png`，不上传整个运行目录。

## 验收场景

- 匿名可浏览架构、组件职责、各数据存储分工和一致性边界，不要求先登录。
- 组件说明采用持久inline inspector而非modal/drawer，不虚构关闭或焦点陷阱需求；可用键盘选择组件，移动端选择后滚动并聚焦说明标题；基础heading、label与按钮名称可访问。
- 注册/登录/退出走真实HttpOnly session+CSRF。
- 真实任务最终显示events、attempts、结果和缓存状态，deterministic明确标识为非真实模型。
- 连续提交事件只能产生一个任务；刷新、前进/后退保留正确选中任务。
- 两个任务切换时，延迟的真实旧响应不能覆盖当前详情；延迟只延后真实response，不伪造数据。
- 退出后清空报告、轨迹等私密数据，停止任务轮询；后退不能还原私密视图。真实logout响应延迟期间，提交必须禁用/撤销，不发送新task；重新登录不恢复旧草稿。
- 同cookie jar另一tab通过GET /auth/me轮换CSRF后，原tab提交仅允许一次有界恢复（403→202），列表任务仅1；再次轮换后logout同样403→204，不禁用CSRF。
- 403由真实错误CSRF请求触发；404使用不存在的task_id；界面显示错误而非成功。
- XSS样式输入作为纯文本呈现，没有DOM注入或脚本执行。
- 1440px桌面与390px移动端没有页面级水平溢出；保存架构/组件页、真实任务结果页和移动截图供人工视觉验收。

## 当前证据

| 检查 | 状态 | 说明 |
|---|---|---|
| npm ci（测试项目） | 已通过 | 使用可写缓存目录 |
| Chromium151下载 | CI已通过；本地环境阻塞 | CI官方151.0.7922.34下载成功；本地CDN曾返回0MiB非ZIP，未降级绕过 |
| Chromium沙箱启动 | CI已通过 | Ubuntu24.04 runner受AppArmor限制；仅UI job迁到官方支持的22.04，sandbox保持开启 |
| 匿名UI浏览器测试 | CI已通过 | 官方151、1440/390共4项；不是仅历史141证据 |
| 真实业务UI浏览器测试 | 14通过 | run39720266829，7场景×桌面/移动全部通过 |
| 完整浏览器套件 | 18通过 / 0错误 / 0跳过 | 独立解析artifact JUnit，真实151浏览器运行56.0秒 |
| 移动布局与列表一致性修复回归 | CI已通过 | 保持18场景，主链路新增真实任务row终态/attempt一致断言，scrollWidth严格对比配置390/1440而不是可被溢出撑大的innerWidth |

最新成功证据：commit `382da456a4a9e646480502d2df81cb0d0ef40045`，run `39720266829`，artifact `12400883061`。UI17单元、18浏览器全部通过。本地解压 `test-results/ci-39720266829/`，包含JUnit、6张匿名架构图、桌面与mobile真实成功图。历史run39719030410为17通过/1mobile点击超时，grid min-width布局与列表终态同步已修复，并保留更严格的断言通过重跑。首次run39718568675的18项均停在sandbox启动，不是18项业务断言失败。

已有后端20单元及9真实集成测试的成功不能代替前端浏览器验收。截图也不能单独证明四组件链路成功。

本地匿名截图：`test-results/ui-preview/` 下 desktop/mobile 的 architecture、mysql-detail、query-redis。未知健康状态保持可见，不是全链路证据。首次移动keyboard测试依赖隐藏节点序号而失败，已修正为实际组件可访问名称并重跑4项通过。

发布前升级：`@playwright/test`精确1.62.1、lock更新；`npm audit --audit-level=high`返回0 vulnerabilities；完整18项成功列出。浏览器官方CDN下载问题单独记录，不把依赖安装成功当作浏览器新版本通过。

## 后续：单 Agent 扩展（独立于上述已验收 UI 基线）

状态：**真实基础设施与浏览器回归已通过**。独立证据为commit `9c4a1908124b61eee4207dc5bb6cb172134fda06`、run `39721645077`，不是沿用382da456的旧18项成功。

- 新增 `tests/e2e/single-agent.spec.ts`：3场景×1440/390，共6项；连同原18项共24项，官方Chromium151真实CI全部通过，0失败/错误/跳过。涵盖脚本read/search/stats的参数/观察逐项对照真实API、与MySQL后台生命周期分区、脚本非真实推理标识、刷新及缓存、XSS文本、退出清理、工具拒绝后not_committed诚实空态、延迟旧动作响应隔离、严格页面宽度检查。
- 新增 `tests/integration/test_single_agent.py`：4项；加原7项与recovery2项共13项，真实CI以11+2项全部通过，0失败/错误/跳过。新文件已明确纳入 `scripts/test-integration.sh` 主pytest，不跳过真实服务。
- 多步持久化检查Mongo原文/SQL attempt/result引用、Redis缓存、真实Kafka重复交付与inbox去重、401/404；两种旧结果fixture验证legacy标识与不可变文档不改写；不支持的数值材料必须永久失败且不能返回未提交动作。
- 原recovery2项增强未完成/失败动作不可见、过期fence旧文档不成为可见动作；原故障编排保留，Mongo读停机时agent-steps必须503而非伪空，Redis停机恢复路径仍可读取已提交动作。
- 脚本示例（不是live LLM）：`目标：[search:销量] [stats]\n材料：销量 10 20 30`。仅离线Model.run校验了浏览器带XSS文本示例仍产生7个动作、count3/sum60/mean20；这不是基础设施或浏览器执行证据。
- 未在云端启动本地浏览器或绕过其沙箱限制；已在授权GitHub CI使用官方151、sandbox开启与真实四组件执行。真实provider验收仍等待独立配置/授权；未启用live或调用npm audit。

单Agent证据复核：独立下载并解析JUnit确认13真实集成与24浏览器通过；CI日志另确认140后端单元、30前端单元通过。两张新增Agent桌面/移动全页图位于 `test-results/ci-39721645077/ui/test-results/browser-artifacts/single-agent-*`；字段逐项对照真实HTTP响应、步骤持久化与缓存语义有断言，不仅是截图。

- UI artifact `12401338075`，ZIP SHA256 `7f43114bf677da1b06d89accb2dba29b4f6e7e88d73b7cb266563ac0f81fd3a1`。
- 真实集成 artifact `12401437064`，ZIP SHA256 `df58d73d5279a09732b5b09b05417e38d6e1904639cc4f20570f844b86f70838`。
- 本地实际计算ZIP摘要与CI上传摘要一致；未上传Library，未记录会话trace。真实LLM仍未调用、未验收。
