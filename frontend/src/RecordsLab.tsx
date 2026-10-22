import { useRef, useState, type FormEvent } from "react";
import { Check, Pencil, Plus, Trash2 } from "lucide-react";
import { ApiError } from "./api";
import {
  type LabProps,
  type MysqlRecord,
  type MongoDocument,
  labTime,
  pretty,
} from "./lab";
import {
  DeleteConfirm,
  Empty,
  JsonView,
  LabError,
  ListTools,
  Pagination,
  useLabList,
  useLabOperation,
} from "./LabShared";

type RecordItem = MysqlRecord | MongoDocument;
export default function RecordsLab({
  kind,
  ...props
}: LabProps & { kind: "mysql" | "mongo" }) {
  const isMongo = kind === "mongo",
    path = `/lab/${kind}/${isMongo ? "documents" : "records"}`;
  const list = useLabList<RecordItem>(path, props.onUnauthorized),
    operation = useLabOperation(props);
  const [selected, setSelected] = useState<string | null>(null),
    [name, setName] = useState(""),
    [value, setValue] = useState("");
  const [document, setDocument] = useState(""),
    [deleted, setDeleted] = useState<RecordItem | null>(null);
  const [result, setResult] = useState<RecordItem | null>(null),
    [notice, setNotice] = useState("");
  const input = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  function clear() {
    setSelected(null);
    setName("");
    setValue("");
    setDocument("");
    setNotice("");
    operation.setError("");
  }
  function stale(error: unknown) {
    if (error instanceof ApiError && error.status === 404) {
      clear();
      setDeleted(null);
      setResult(null);
      operation.setError(
        `这条教学数据已不存在，可能被另一个页面删除。列表已重新读取，请重新选择。${error.requestId ? `（请求 ID：${error.requestId}）` : ""}`,
      );
      list.refresh();
    }
  }
  function save(e: FormEvent) {
    e.preventDefault();
    setNotice("");
    setResult(null);
    let body: unknown = { name: name.trim(), value };
    if (isMongo) {
      try {
        const parsed: unknown = JSON.parse(document);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
          throw new Error("文档必须是 JSON 对象，不能是数组或单个值。");
        body = { document: parsed };
      } catch (error) {
        operation.setError(
          error instanceof SyntaxError
            ? "JSON 格式不正确。请检查双引号、逗号和括号后重试。"
            : (error as Error).message,
        );
        return;
      }
    }
    void operation.run(
      () =>
        operation.write<RecordItem>(selected ? `${path}/${selected}` : path, {
          method: selected ? "PUT" : "POST",
          body: JSON.stringify(body),
        }),
      (saved) => {
        setResult(saved);
        setSelected(null);
        setName("");
        setValue("");
        setDocument("");
        setNotice("服务端已保存。下方显示真实写入响应；列表将重新读取。");
        list.reset();
      },
      (error) => {
        stale(error);
        if (!(error instanceof ApiError) || error.status >= 500)
          setNotice(
            "写入结果可能尚未确认。请先刷新列表核对，避免重复创建；草稿已保留。",
          );
      },
    );
  }
  function edit(item: RecordItem) {
    setNotice("");
    void operation.run(
      () => operation.read<RecordItem>(`${path}/${item.id}`),
      (fresh) => {
        setSelected(fresh.id);
        setResult(fresh);
        setNotice(
          "已重新读取这条数据。保存会替换其内容，共享空间没有多人编辑锁。",
        );
        if ("document" in fresh) setDocument(pretty(fresh.document));
        else {
          setName(fresh.name);
          setValue(fresh.value);
        }
        input.current?.focus();
      },
      stale,
    );
  }
  return (
    <div className="lab-workbench-grid">
      <section className="lab-panel lab-editor">
        <div className="lab-section-title">
          <h2>
            {selected
              ? isMongo
                ? "替换文档"
                : "编辑记录"
              : isMongo
                ? "保存 JSON 文档"
                : "新建记录"}
          </h2>
          <Plus size={17} />
        </div>
        {selected && (
          <p className="lab-small">
            正在编辑 <code>{selected}</code>
          </p>
        )}
        <form onSubmit={save}>
          {isMongo ? (
            <>
              <label htmlFor="mongo-document">JSON 文档</label>
              <textarea
                id="mongo-document"
                ref={input}
                className="code-input"
                value={document}
                onChange={(e) => setDocument(e.target.value)}
                placeholder={
                  '{\n  "title": "我的第一份文档",\n  "tags": ["学习", "后端"]\n}'
                }
                rows={9}
                required
                disabled={operation.busy}
              />
              <p className="lab-help">
                仅接受对象，最多 16 KiB、6 层深度、200 个节点。键名不能含点、NUL
                或以 $ 开头；这里不是 Mongo 查询控制台。大编号请用字符串，避免
                JavaScript 数字精度限制。
              </p>
            </>
          ) : (
            <>
              <label htmlFor="mysql-name">名称</label>
              <input
                id="mysql-name"
                ref={input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：第一条学习笔记"
                maxLength={80}
                required
                disabled={operation.busy}
              />
              <label htmlFor="mysql-value">内容</label>
              <textarea
                id="mysql-value"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="写下你想保存的内容"
                maxLength={1000}
                rows={5}
                disabled={operation.busy}
              />
              <p className="lab-help">
                名称最多 80 字，内容最多 1000 字。通过受限 API
                操作独立教学表，不执行原始 SQL。
              </p>
            </>
          )}
          <div className="lab-actions">
            <button
              className="primary"
              disabled={
                operation.busy || (isMongo ? !document.trim() : !name.trim())
              }
            >
              {operation.busy
                ? "处理中…"
                : selected
                  ? "保存修改"
                  : isMongo
                    ? "保存文档"
                    : "创建记录"}
            </button>
            {selected && (
              <button
                type="button"
                className="lab-button"
                disabled={operation.busy}
                onClick={clear}
              >
                取消编辑
              </button>
            )}
          </div>
        </form>
        {operation.error && <LabError>{operation.error}</LabError>}
        {notice && (
          <p className="lab-notice" role="status">
            <Check size={15} />
            {notice}
          </p>
        )}
        {operation.busy && (
          <p className="lab-help">
            请勿重复提交。离开页面不会撤销服务端已收到的写入。
          </p>
        )}
        {result && (
          <details className="lab-response">
            <summary>服务端返回的数据</summary>
            <JsonView value={result} />
          </details>
        )}
      </section>
      <section
        className="lab-panel lab-results"
        aria-label={isMongo ? "已保存的文档" : "已保存的记录"}
      >
        <div className="lab-section-title">
          <h2>{isMongo ? "已保存的文档" : "已保存的记录"}</h2>
          <ListTools
            loading={list.loading}
            refresh={list.refresh}
            disabled={operation.busy}
          />
        </div>
        <p className="lab-help">
          从服务端读取 · 本地帐号共享 ·{" "}
          {isMongo
            ? "保存后可以刷新或重新打开验证"
            : "每条记录都有固定字段和服务端 ID"}
        </p>
        {list.error && (
          <LabError>
            读取失败：{list.error}
            {list.data && " 当前保留上一次读取的内容，并非最新状态。"}
          </LabError>
        )}
        {!list.data && list.loading ? (
          <Empty>
            <span role="status">正在读取教学数据…</span>
          </Empty>
        ) : !list.data ? (
          <Empty>尚未取得数据。服务恢复后点击「刷新列表」。</Empty>
        ) : !list.data.items.length ? (
          <Empty>
            还没有{isMongo ? "文档" : "记录"}。在左侧保存一条，再在这里查看。
          </Empty>
        ) : isMongo ? (
          <div className="document-list">
            {list.data.items.map((item) => (
              <article className="document-item" key={item.id}>
                <div className="document-heading">
                  <code>{item.id}</code>
                  <div className="lab-row-actions">
                    <button
                      className="lab-button"
                      disabled={operation.busy}
                      onClick={() => edit(item)}
                      aria-label={`编辑文档 ${item.id}`}
                    >
                      <Pencil size={14} />
                      编辑
                    </button>
                    <button
                      className="lab-button"
                      disabled={operation.busy}
                      onClick={() => {
                        operation.setError("");
                        setDeleted(item);
                      }}
                      aria-label={`删除文档 ${item.id}`}
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                </div>
                <JsonView value={(item as MongoDocument).document} />
                <small>更新于 {labTime(item.updated_at)}</small>
              </article>
            ))}
          </div>
        ) : (
          <div className="lab-table-scroll">
            <table className="lab-table">
              <thead>
                <tr>
                  <th>名称 / ID</th>
                  <th>内容</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{(item as MysqlRecord).name}</strong>
                      <code>{item.id}</code>
                    </td>
                    <td className="lab-value">
                      {(item as MysqlRecord).value || (
                        <span className="muted">空字符串</span>
                      )}
                    </td>
                    <td>
                      <time dateTime={item.updated_at}>
                        {labTime(item.updated_at)}
                      </time>
                    </td>
                    <td>
                      <div className="lab-row-actions">
                        <button
                          className="lab-button"
                          disabled={operation.busy}
                          onClick={() => edit(item)}
                          aria-label={`编辑 ${(item as MysqlRecord).name}`}
                        >
                          <Pencil size={14} />
                          编辑
                        </button>
                        <button
                          className="lab-button"
                          disabled={operation.busy}
                          onClick={() => {
                            operation.setError("");
                            setDeleted(item);
                          }}
                          aria-label={`删除 ${(item as MysqlRecord).name}`}
                        >
                          <Trash2 size={14} />
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination
          data={list.data}
          offset={list.offset}
          setOffset={list.setOffset}
          disabled={list.loading || operation.busy}
        />
      </section>
      {deleted && (
        <DeleteConfirm
          target={"name" in deleted ? deleted.name : deleted.id}
          busy={operation.busy}
          cancel={() => setDeleted(null)}
          confirm={() =>
            void operation.run(
              () =>
                operation.write<void>(`${path}/${deleted.id}?confirm=true`, {
                  method: "DELETE",
                }),
              () => {
                if (selected === deleted.id) clear();
                if (result?.id === deleted.id) setResult(null);
                setDeleted(null);
                setNotice("服务端已确认删除这条教学数据。");
                list.refresh();
              },
              (e) => {
                setDeleted(null);
                stale(e);
              },
            )
          }
        />
      )}
    </div>
  );
}
