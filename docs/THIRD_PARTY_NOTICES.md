# 第三方依赖、镜像与引用来源清单

核对日期：2026-10-22。用途：让学习者知道项目依赖什么、许可信息来自哪里，以及哪些事项仍需复核。**这是一份来源索引和有限核对记录，不是完整 SBOM、分发许可包、漏洞报告或法律合规结论。**

本项目自身尚未选择许可证；仓库公开不代表维护者已批准 MIT、Apache-2.0 或其他授权。上游许可不自动成为本项目许可，也不会因引用而改变。正式许可证与版权主体须由所有者确认；本页不新增 `LICENSE`，不将第三方内容重新许可。参见 [GitHub 许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。

## 1. 清单范围与证据级别

版本以本仓库 [pyproject.toml](../pyproject.toml)、[uv.lock](../uv.lock)、[前端 lock](../frontend/package-lock.json)、[浏览器测试 lock](../tests/e2e/package-lock.json)、Dockerfile 和清单为准，不是上游“最新版”声明。本次只读取锁文件、已安装包元数据/部分许可文件和公开上游资料，**没有上传 lockfile/依赖图到外部扫描器，没有运行 `npm audit`**。

| 标记 | 本页实际核对了什么 | 不能推出什么 |
|---|---|---|
| P | 锁定版本与本地同版本 Python `dist-info/METADATA` 的许可/项目来源字段 | 不代表逐文件审计全部 wheel 或所有传递依赖 |
| N | npm lock 的版本/许可，与已安装同版本 `package.json` 的来源字段 | 不代表打包内容、构建产物和传递依赖已全部审计 |
| L | 额外读取该包自带 LICENSE/NOTICE 或固定版本上游许可正文 | 不代表整个平台、整个镜像的每个组件使用同一许可 |
| R | 复用 [官方学习资源目录](OPEN_SOURCE_RESOURCES.md) 中已核对的固定版本上游证据 | 代码主许可不自动覆盖外部网站文档或商标 |
| U | 本次未完成核验，必须在相应再分发/部署前补齐 | 不能标“已兼容”“无漏洞”或“全部开源” |

本地依赖目录不提交入库；读者可在按锁文件安装后检查对应包的元数据和许可文件。下表来源链接主要定位维护者仓库；标 P/N 的条目不是声称再次逐一访问了其全部版本许可页。

## 2. 后端直接依赖与开发测试工具

以下九个运行依赖、两个 dev 依赖来自 `pyproject.toml`，版本来自 `uv.lock`。

| 包 | 锁定版本 | 许可信息 | 来源 / 状态 |
|---|---|---|---|
| fastapi | 0.159.1 | MIT | [fastapi/fastapi](https://github.com/fastapi/fastapi)，P / R |
| uvicorn | 0.54.0 | BSD-3-Clause | [Kludex/uvicorn](https://github.com/Kludex/uvicorn)，P |
| sqlalchemy | 2.1.6 | MIT | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy)，P / R |
| pymysql（启用 rsa extra） | 1.2.3 | MIT；extra 引入的依赖另算 | [PyMySQL/PyMySQL](https://github.com/PyMySQL/PyMySQL)，P |
| pymongo | 4.19.0 | Apache-2.0；不是 MongoDB 服务端的 SSPL | [mongodb/mongo-python-driver](https://github.com/mongodb/mongo-python-driver)，P |
| redis（Python 客户端） | 6.4.0 | MIT；不是 Redis 7.4 服务端许可 | [redis/redis-py](https://github.com/redis/redis-py)，P |
| confluent-kafka | 2.16.0 | Python 源码主许可 Apache-2.0；二进制 wheel 含额外许可声明 | [confluentinc/confluent-kafka-python](https://github.com/confluentinc/confluent-kafka-python)，P / L；见下文 |
| httpx | 0.28.1 | BSD-3-Clause | [encode/httpx](https://github.com/encode/httpx)，P |
| prometheus-client | 0.26.0 | **Apache-2.0 AND BSD-2-Clause**（包元数据表达式） | [prometheus/client_python](https://github.com/prometheus/client_python)，P / L / R；见下文 |
| pytest（dev） | 8.4.2 | MIT | [pytest-dev/pytest](https://github.com/pytest-dev/pytest)，P |
| ruff（dev） | 0.17.1 | MIT | [astral-sh/ruff](https://github.com/astral-sh/ruff)，P |

两个不能只看主许可证的例子：

- `prometheus-client` 的上游主 LICENSE 是 Apache-2.0，但安装包 `NOTICE` 明确包含 BSD-2-Clause 的 `decorator 4.0.10`，所以包元数据为组合表达式。再分发时不能只保留 Apache 标题而忽略 NOTICE / 对应源文件声明。
- `confluent-kafka` 自带 LICENSE 区分 Python 源码与 wheel，后者另列 OpenSSL、zlib、librdkafka 及所含代码的声明。本次已发现并读取这些边界，**未完成实际 wheel 所有原生库、版本和分发义务的逐项审计**，不能把整个 wheel 简写成只有 Apache-2.0。

应用还直接导入由依赖传入的 `pydantic==2.14.1`（MIT）和 `starlette==1.9.0`（BSD-3-Clause）；`pymysql[rsa]` 当前带入 `cryptography==50.0.2`（元数据：Apache-2.0 OR BSD-3-Clause）。这些条目已做 P 级核对，来源分别为 [Pydantic](https://github.com/pydantic/pydantic)、[Starlette](https://github.com/Kludex/starlette)、[Cryptography](https://github.com/pyca/cryptography)。这里只补充易混淆项，**不是完整传递依赖表**。

### 不在根 uv.lock 安装路径中的工具

| 工具 | 仓库固定版本 / 位置 | 许可来源 / 核对状态 |
|---|---|---|
| uv | 0.13.4；[Dockerfile.api](../Dockerfile.api)、CI bootstrap | [MIT](https://github.com/astral-sh/uv/blob/0.13.4/LICENSE-MIT) OR [Apache-2.0](https://github.com/astral-sh/uv/blob/0.13.4/LICENSE-APACHE)，上游 [README](https://github.com/astral-sh/uv/blob/0.13.4/README.md) 明确可选，L；其依赖未全审计 |
| PyYAML | 6.0.3；[CI](../.github/workflows/ci.yml) 结构检查 | [6.0.3 LICENSE](https://github.com/yaml/pyyaml/blob/6.0.3/LICENSE)，MIT，L；原生扩展另需核对 |
| pytest（集成镜像） | 8.3.5；[Dockerfile.test](../Dockerfile.test) 显式安装 | [8.3.5 LICENSE](https://github.com/pytest-dev/pytest/blob/8.3.5/LICENSE)，MIT，L；与根 lock 的 8.4.2 不同，不能合并写成一个版本 |

GitHub Actions 还引用 `actions/checkout@v4`、`actions/setup-python@v5`、`actions/setup-node@v4`、`actions/upload-artifact@v4`。它们是 CI 外部执行代码，不是应用运行依赖；当前用主版本 tag 而非完整 commit，所解析内容与捆绑依赖许可 **U**。不能把本清单称为完整 CI 供应链审计。

## 3. 前端、前端测试与浏览器测试直接依赖

前三项为前端运行依赖，其余为开发/测试依赖；最后一项位于独立的 `tests/e2e` 项目。版本和许可均做 N 级核对。

| 包 | 锁定版本 | 许可信息 | 上游来源 / 补充核对 |
|---|---|---|---|
| lucide-react | 0.468.0 | ISC；许可文件另保留源自 Feather 的 MIT 部分署名 | [lucide-icons/lucide](https://github.com/lucide-icons/lucide)，N / L |
| react | 19.1.1 | MIT | [facebook/react](https://github.com/facebook/react)，N / L |
| react-dom | 19.1.1 | MIT | [facebook/react](https://github.com/facebook/react)，N |
| @testing-library/jest-dom | 6.8.0 | MIT | [testing-library/jest-dom](https://github.com/testing-library/jest-dom)，N |
| @testing-library/react | 16.3.0 | MIT | [react-testing-library](https://github.com/testing-library/react-testing-library)，N |
| @types/react | 19.1.10 | MIT | [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped)，N |
| @types/react-dom | 19.1.9 | MIT | [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped)，N |
| @vitejs/plugin-react | 4.7.0 | MIT | [vite-plugin-react](https://github.com/vitejs/vite-plugin-react)，N |
| jsdom | 26.1.0 | MIT | [jsdom/jsdom](https://github.com/jsdom/jsdom)，N |
| prettier | 3.6.2 | MIT | [prettier/prettier](https://github.com/prettier/prettier)，N |
| typescript | 5.9.2 | Apache-2.0 | [microsoft/TypeScript](https://github.com/microsoft/TypeScript)，N / L |
| vite | 6.4.5 | MIT | [vitejs/vite](https://github.com/vitejs/vite)，N |
| vitest | 5.0.5 | MIT | [vitest-dev/vitest](https://github.com/vitest-dev/vitest)，N |
| @playwright/test | 1.62.1 | Apache-2.0 | [microsoft/playwright](https://github.com/microsoft/playwright)，N / L |

Playwright 包许可证不等于所下载 Chromium、编解码器或系统依赖的统一许可证。浏览器二进制、前端打包结果中的实际第三方内容与全部 npm 传递依赖尚未逐项审计（U）。本清单不是可替代构建产物内版权/许可声明的完整文本。

## 4. 固定版本镜像：主程序与镜像内容分开

固定 tag 便于复现，但 tag 可变；仓库尚未将这些镜像固定为 digest。本次没有拉取/解包镜像作 OS 包与全部层审计。下列许可只定位 **主程序**，每个镜像的基础系统、插件、原生库及打包脚本仍有独立声明。

| 镜像引用 | 使用范围 | 主程序许可与固定版本证据 | 核对状态 |
|---|---|---|---|
| `mysql:8.4.7` | 默认 Compose；K8s/完整草稿复用 | Community Server GPLv2；[mysql-8.4.7 LICENSE](https://github.com/mysql/mysql-server/blob/mysql-8.4.7/LICENSE) 另含附加许可/第三方声明 | R；完整镜像 U |
| `apache/kafka:4.0.0` | 默认 Compose；草稿复用 | Apache-2.0；[4.0.0 LICENSE](https://github.com/apache/kafka/blob/4.0.0/LICENSE) | R；完整镜像 U |
| `mongo:8.0.6` | 默认 Compose；草稿复用 | **SSPL v1，source-available，不是 OSI 开源许可**；[r8.0.6 LICENSE](https://github.com/mongodb/mongo/blob/r8.0.6/LICENSE-Community.txt) | R；完整镜像 U |
| `redis:7.4.2` | 默认 Compose；草稿复用 | **RSALv2 或 SSPLv1，source-available，不是 OSI 开源许可**；[7.4.2 LICENSE](https://github.com/redis/redis/blob/7.4.2/LICENSE.txt) | R；完整镜像 U |
| `python:3.12.10-slim-bookworm` | API 构建基础 | PSF License v2 与所列附加/历史许可；[v3.12.10 LICENSE](https://github.com/python/cpython/blob/v3.12.10/LICENSE) | L；Debian/完整镜像 U |
| `node:24.22.1-alpine` | 可选前端构建阶段 | Node 主体 MIT，文件另列 bundled software；[v24.22.1 LICENSE](https://github.com/nodejs/node/blob/v24.22.1/LICENSE) | L；Alpine/完整镜像 U |
| `nginx:1.28.3-alpine` | 可选前端同源网关 | BSD-2-Clause；[release-1.28.3 LICENSE](https://github.com/nginx/nginx/blob/release-1.28.3/LICENSE) | L；Alpine/完整镜像 U |
| `prom/prometheus:v3.3.0` | 仅完整基础设施草稿，非默认验收服务 | Apache-2.0；[v3.3.0 LICENSE](https://github.com/prometheus/prometheus/blob/v3.3.0/LICENSE) | R；完整镜像 U |
| `grafana/grafana:12.0.0` | 仅完整基础设施草稿 | AGPLv3 主许可；[v12.0.0 LICENSE](https://github.com/grafana/grafana/blob/v12.0.0/LICENSE) | L；插件/完整镜像 U |
| `otel/opentelemetry-collector:0.123.0` | 仅完整基础设施草稿 | Apache-2.0；[v0.123.0 LICENSE](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.123.0/LICENSE) | R；完整镜像 U |
| `kindest/node:v1.32.2` | Kind 草稿，本轮延期 | Kubernetes 主体 Apache-2.0；[v1.32.2 LICENSE](https://github.com/kubernetes/kubernetes/blob/v1.32.2/LICENSE)，不是整个 Kind 节点统一许可 | R；节点镜像 U |

引用位置：[默认 Compose](../compose.yaml)、[UI overlay](../compose.ui.yaml)、[Dockerfile.api](../Dockerfile.api)、[Dockerfile.frontend](../Dockerfile.frontend)；后续部署范围见 [Kubernetes 说明](../infra/k8s/README.md)（当前无 Kind 或完整基础设施草稿配置）。`agent-stack-lab-api/tests/gateway:local` 与 `:ci` 是本项目构建标记，不是已发布的第三方镜像或 digest 锁定。

特别注意：Redis [官方版本许可表](https://redis.io/legal/licenses/) 区分 7.2 及以前、7.4、8+，不能把旧 BSD 或新版可选 AGPLv3 套到 7.4.2；MongoDB [官方许可说明](https://www.mongodb.com/legal/licensing/community-edition) 区分服务端、驱动和文档，OSI 也明确说明 [SSPL 不是开源许可证](https://opensource.org/blog/the-sspl-is-not-an-open-source-license)。客户端 MIT/Apache-2.0 不能证明服务端采用相同许可。

## 5. 引用文档与原创学习摘要

[OPEN_SOURCE_RESOURCES](OPEN_SOURCE_RESOURCES.md) 是主要引用入口，本仓库保留外链和原创中文导读/练习，**没有将第三方手册整篇复制或作为本项目文档重新许可**。下表登记引用主体和许可核对边界，不把公开网页与代码许可证混为一谈。

| 文档主体 | 引用内容 / 官方入口 | 当前复用方式与核对边界 |
|---|---|---|
| FastAPI | [请求体](https://fastapi.tiangolo.com/tutorial/body/)、并发 | 外链/原创摘要；代码 MIT 已核对，目标网页复制许可未逐页审计 |
| Pydantic | [v2 validators](https://pydantic.dev/docs/validation/latest/concepts/validators/) | 外链/原创摘要；代码 MIT 已核对，滚动文档需按锁定版本理解 |
| SQLAlchemy | [2.1 Session](https://docs.sqlalchemy.org/en/21/orm/session_basics.html) | 外链/原创摘要；代码 MIT 已核对，网页复用须另看声明 |
| MySQL | [8.4 locking reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html) | 外链/原创摘要；手册许可不能由 GPL 服务端主许可推出 |
| Apache Kafka | [4.0 design](https://kafka.apache.org/40/design/design/) | 外链/原创摘要；代码 Apache-2.0 已核对，复制时再查文档文件及 NOTICE |
| MongoDB | [8.0 atomicity](https://www.mongodb.com/docs/v8.0/core/write-operations-atomicity/) | 外链/原创摘要；文档、驱动、SSPL 服务端各有边界 |
| Redis | [cache-aside](https://redis.io/docs/latest/develop/use-cases/cache-aside/) | 外链/原创摘要；网站文章与 7.4.2 服务端双许可不混用 |
| Docker | [Compose 启动顺序](https://docs.docker.com/compose/how-tos/startup-order/) | 外链/原创摘要；Compose 代码 Apache-2.0 不代表 Docker Docs 或 Desktop 订阅条款 |
| Prometheus | [Python instrumentation](https://prometheus.github.io/client_python/instrumenting/)、[实践](https://prometheus.io/docs/practices/instrumentation/) | 外链/原创摘要；客户端、服务端、网页分别核对 |
| OpenTelemetry | [可观测性概念](https://opentelemetry.io/docs/concepts/observability-primer/) | 后续阅读外链；Collector 主许可不代替所有网页许可 |
| Kubernetes | [探针](https://kubernetes.io/docs/concepts/workloads/pods/probes/)、网络策略 | 后续阅读外链；代码 Apache-2.0 已核对，网站内容复制条款未逐页审计 |
| GitHub / OSI | [仓库许可说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)、[私密报告](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)、许可证分类 | 外链与简短原创说明，不复制整篇；不构成针对本项目的法律意见 |

今后要复制代码、翻译/转载段落、分发图标或截图时，必须核对 **具体文件/页面及版本**、署名、NOTICE、修改标记、商标和分发条件；链接到来源本身不能代替授权。需要许可原文随制品分发时，本索引也不能代替原文。

## 6. 未完成项与更新方法

- **未完成**：全部 Python/npm 传递依赖、编译入 wheel 的库、所有镜像 OS/捆绑包、Chromium/system dependencies、CI Actions 解析版本、所有文档逐页复制许可与最终二进制/容器制品的分发义务审计。
- **未作结论**：与将来本项目许可证的整体兼容性、特定商业/托管方案许可适用性、所有组件当前支持期或无漏洞保证。不能因若干直接依赖为 MIT 就概括为“全栈 MIT”。
- **源代码学习型交付**：保留来源、明确上述未知项，不假装已经发布第三方容器/打包制品。正式开源采用许可证仍等待所有者选择；未来对外分发制品或提供托管服务前，需按实际交付内容补充针对性审查。
- **每次依赖/镜像更新**：重新列出实际锁定版本与来源，读取发行包许可/NOTICE，记录新增或变化项；不要只替换表中的版本数字。若需外部扫描，先确认发送的数据与授权，再执行。

本页只提供事实定位，不替代许可原文或专业法律判断。发布门槛与有限 v1 范围见 [RELEASE_CHECKLIST](RELEASE_CHECKLIST.md)。
