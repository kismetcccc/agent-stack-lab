import { useState, type FormEvent } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { ApiError } from "./api";
import {
  type LabProps,
  type MysqlRecord,
  type MongoDocument,
  labTime,
  pretty,
} from "./lab";
import ConsoleDrawer from "./ConsoleDrawer";
import { useNavigationGuard } from "./navigation";
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
type DrawerMode = "create" | "edit" | "detail" | null;
const draftKey = (name: string, value: string, document: string) =>
  JSON.stringify([name, value, document]);

export default function RecordsLab({
  kind,
  ...props
}: LabProps & { kind: "mysql" | "mongo" }) {
  const isMongo = kind === "mongo",
    path = `/lab/${kind}/${isMongo ? "documents" : "records"}`;
  const list = useLabList<RecordItem>(path, props.onUnauthorized),
    operation = useLabOperation(props);
  const requestLeave = useNavigationGuard();
  const [drawer, setDrawer] = useState<DrawerMode>(null),
    [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState(""),
    [value, setValue] = useState(""),
    [document, setDocument] = useState("");
  const [baseline, setBaseline] = useState(draftKey("", "", "")),
    [deleted, setDeleted] = useState<RecordItem | null>(null);
  const [result, setResult] = useState<RecordItem | null>(null),
    [notice, setNotice] = useState("");
  const editing = drawer === "create" || drawer === "edit";
  const dirty = editing && baseline !== draftKey(name, value, document);

  function close() {
    operation.invalidate();
    setDrawer(null);
    setSelected(null);
    setName("");
    setValue("");
    setDocument("");
    setResult(null);
    setNotice("");
  }
  function openCreate() {
    requestLeave(() => {
      close();
      setBaseline(draftKey("", "", ""));
      setDrawer("create");
    });
  }
  function stale(error: unknown) {
    if (error instanceof ApiError && error.status === 404) {
      setSelected(null);
      setDeleted(null);
      setResult(null);
      setDrawer(null);
      setName("");
      setValue("");
      setDocument("");
      setNotice("");
      operation.setError(
        `这条教学数据已不存在，可能被另一个页面删除。列表已重新读取，请重新选择。${error.requestId ? `（请求 ID：${error.requestId}）` : ""}`,
      );
      list.refresh();
    }
  }
  function select(item: RecordItem, mode: "edit" | "detail") {
    requestLeave(() => {
      operation.invalidate();
      setNotice("");
      setResult(null);
      setSelected(item.id);
      setName("");
      setValue("");
      setDocument("");
      setBaseline(draftKey("", "", ""));
      setDrawer(mode);
      void operation.run(
        () => operation.read<RecordItem>(`${path}/${item.id}`),
        (fresh) => {
          setResult(fresh);
          const nextName = "name" in fresh ? fresh.name : "";
          const nextValue = "value" in fresh ? fresh.value : "";
          const nextDocument =
            "document" in fresh ? pretty(fresh.document) : "";
          setName(nextName);
          setValue(nextValue);
          setDocument(nextDocument);
          setBaseline(draftKey(nextName, nextValue, nextDocument));
        },
        stale,
      );
    });
  }
  function save(e: FormEvent) {
    e.preventDefault();
    if (operation.busy || (drawer === "edit" && !result)) return;
    setNotice("");
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
            ? `JSON 格式不正确：${error.message}。请检查双引号、逗号和括号。`
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
        setSelected(saved.id);
        setDrawer("detail");
        setName("");
        setValue("");
        setDocument("");
        setNotice(
          "服务端已保存。当前显示写入响应；列表正独立重新读取，请核对列表读取状态。",
        );
        list.refresh();
      },
      (error) => {
        stale(error);
        if (!(error instanceof ApiError) || error.status >= 500)
          setNotice(
            "写入结果可能尚未确认。请先刷新列表核对，避免重复创建；草稿已保留，关闭不会撤销已送达的写入。",
          );
      },
    );
  }
  const title =
    drawer === "create"
      ? isMongo
        ? "新建文档"
        : "新建记录"
      : drawer === "edit"
        ? isMongo
          ? "替换文档"
          : "编辑记录"
        : isMongo
          ? "文档详情"
          : "记录详情";
  return (
    <div className="lab-resource-workspace">
      <section
        data-testid="resource-primary"
        className="lab-panel lab-results"
        aria-label={isMongo ? "已保存的文档" : "已保存的记录"}
      >
        <div className="lab-toolbar">
          <button
            className="primary"
            onClick={openCreate}
            disabled={operation.busy}
          >
            <Plus size={15} />
            {isMongo ? "新建文档" : "新建记录"}
          </button>
          <ListTools
            loading={list.loading}
            refresh={list.refresh}
            disabled={operation.busy}
          />
        </div>
        {list.error && (
          <LabError>
            读取失败：{list.error}
            {list.data && " 当前保留上一次读取的内容，并非最新状态。"}
          </LabError>
        )}
        {operation.error && !drawer && <LabError>{operation.error}</LabError>}
        {notice && !drawer && (
          <p className="lab-notice" role="status">
            {notice}
          </p>
        )}
        {!list.data && list.loading ? (
          <Empty>
            <span role="status">正在读取教学数据…</span>
          </Empty>
        ) : !list.data ? (
          <Empty>尚未取得数据。服务恢复后点击「刷新列表」。</Empty>
        ) : !list.data.items.length ? (
          <Empty>
            还没有{isMongo ? "文档" : "记录"}。点击「
            {isMongo ? "新建文档" : "新建记录"}」保存第一条。
          </Empty>
        ) : (
          <div className="lab-table-scroll">
            <table
              className={`lab-table ${isMongo ? "mongo-index" : "mysql-records"}`}
            >
              <thead>
                <tr>
                  {isMongo ? (
                    <>
                      <th>文档 ID</th>
                      <th>字段摘要</th>
                    </>
                  ) : (
                    <>
                      <th>名称</th>
                      <th>内容摘要</th>
                      <th>ID</th>
                    </>
                  )}
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item) => (
                  <tr key={item.id} data-resource-id={item.id}>
                    <td>
                      <button
                        className="lab-link"
                        disabled={operation.busy}
                        onClick={() => select(item, "detail")}
                        aria-label={
                          isMongo
                            ? `查看文档 ${item.id}`
                            : `查看记录 ${(item as MysqlRecord).name}`
                        }
                      >
                        {isMongo ? (
                          <code>{item.id}</code>
                        ) : (
                          (item as MysqlRecord).name
                        )}
                      </button>
                    </td>
                    <td className="lab-value">
                      <span
                        className="lab-cell-summary"
                        title={
                          isMongo
                            ? Object.keys(
                                (item as MongoDocument).document,
                              ).join("、")
                            : (item as MysqlRecord).value
                        }
                      >
                        {isMongo
                          ? `${Object.keys((item as MongoDocument).document).length} 个顶层字段 · ${
                              Object.keys((item as MongoDocument).document)
                                .slice(0, 5)
                                .join("、") || "空对象"
                            }`
                          : (item as MysqlRecord).value || "空字符串"}
                      </span>
                    </td>
                    {!isMongo && (
                      <td>
                        <code>{item.id}</code>
                      </td>
                    )}
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
                          onClick={() => select(item, "edit")}
                          aria-label={
                            isMongo
                              ? `替换文档 ${item.id}`
                              : `编辑 ${(item as MysqlRecord).name}`
                          }
                        >
                          <Pencil size={14} />
                          {isMongo ? "替换文档" : "编辑"}
                        </button>
                        <button
                          className="lab-button"
                          disabled={operation.busy}
                          onClick={() => {
                            operation.setError("");
                            setDeleted(item);
                          }}
                          aria-label={
                            isMongo
                              ? `删除文档 ${item.id}`
                              : `删除 ${(item as MysqlRecord).name}`
                          }
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
      <ConsoleDrawer
        open={!!drawer}
        title={title}
        onClose={close}
        dirty={dirty}
        busy={operation.busy}
        wide={isMongo}
      >
        {editing ? (
          <div className="lab-editor">
            {selected && (
              <p className="lab-small">
                服务端 ID <code>{selected}</code>
              </p>
            )}
            {drawer === "edit" && !result ? (
              <Empty>
                {operation.busy
                  ? "正在重新读取最新数据…"
                  : "未取得最新数据，不能提交修改。请关闭后重试。"}
              </Empty>
            ) : (
              <form onSubmit={save}>
                {isMongo ? (
                  <>
                    <label htmlFor="mongo-document">JSON 文档</label>
                    <textarea
                      id="mongo-document"
                      className="code-input"
                      value={document}
                      onChange={(e) => setDocument(e.target.value)}
                      placeholder={'{\n  "title": "我的第一份文档"\n}'}
                      rows={14}
                      required
                      disabled={operation.busy}
                    />
                    <p className="lab-help">
                      仅 JSON 对象；最多 16 KiB、6 层、200
                      节点。键名不能含点、NUL 或以 $ 开头。大编号请用字符串。
                    </p>
                    {selected && (
                      <p className="lab-inline-warning">
                        完整替换，不是字段合并；未提交的旧字段将被移除。
                      </p>
                    )}
                  </>
                ) : (
                  <>
                    <label htmlFor="mysql-name">名称</label>
                    <input
                      id="mysql-name"
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
                      rows={7}
                      disabled={operation.busy}
                    />
                    <p className="lab-help">
                      名称最多 80 字，内容最多 1000 字。共享教学表，不执行原始
                      SQL。
                    </p>
                  </>
                )}
                {selected && (
                  <p className="lab-help">
                    已按 ID 重新读取；共享空间没有多人编辑锁。
                  </p>
                )}
                <div className="lab-actions">
                  <button
                    className="primary"
                    disabled={
                      operation.busy ||
                      (isMongo ? !document.trim() : !name.trim())
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
                  <button
                    type="button"
                    className="lab-button"
                    onClick={() => requestLeave(close)}
                  >
                    {selected ? "取消编辑" : "取消"}
                  </button>
                </div>
              </form>
            )}
          </div>
        ) : result ? (
          <section className="lab-record-detail" aria-label={title}>
            <dl className="lab-detail-fields">
              <dt>服务端 ID</dt>
              <dd>
                <code>{result.id}</code>
              </dd>
              {"name" in result && (
                <>
                  <dt>名称</dt>
                  <dd>{result.name}</dd>
                  <dt>内容</dt>
                  <dd className="lab-detail-value">
                    {result.value || "（空字符串）"}
                  </dd>
                </>
              )}
              <dt>创建时间</dt>
              <dd>
                <time dateTime={result.created_at}>
                  {labTime(result.created_at)}
                </time>
              </dd>
              <dt>更新时间</dt>
              <dd>
                <time dateTime={result.updated_at}>
                  {labTime(result.updated_at)}
                </time>
              </dd>
            </dl>
            {"document" in result && (
              <div>
                <h3>document</h3>
                <JsonView value={result.document} />
              </div>
            )}
            <details className="lab-response">
              <summary>响应详情</summary>
              <JsonView value={result} />
            </details>
            <div className="lab-actions">
              <button
                className="lab-button"
                disabled={operation.busy}
                onClick={() => select(result, "edit")}
              >
                {isMongo ? "替换文档" : "编辑记录"}
              </button>
            </div>
          </section>
        ) : (
          <Empty>
            {operation.busy ? "正在读取详情…" : "未取得详情，请关闭后重试。"}
          </Empty>
        )}
        {operation.error && <LabError>{operation.error}</LabError>}
        {notice && (
          <p className="lab-notice" role="status">
            {notice}
          </p>
        )}
        {drawer === "detail" && list.error && (
          <LabError>
            写入响应与列表回读是两步。列表读取失败：{list.error}
          </LabError>
        )}
        {operation.busy && (
          <p className="lab-help">
            处理中，请勿重复提交。关闭或离开页面不会撤销服务端已收到的写入。
          </p>
        )}
      </ConsoleDrawer>
      {deleted && (
        <DeleteConfirm
          target={
            "name" in deleted ? `${deleted.name}（${deleted.id}）` : deleted.id
          }
          busy={operation.busy}
          cancel={() => setDeleted(null)}
          confirm={() =>
            void operation.run(
              () =>
                operation.write<void>(`${path}/${deleted.id}?confirm=true`, {
                  method: "DELETE",
                }),
              () => {
                setDeleted(null);
                setNotice("服务端已确认删除这条教学数据。");
                list.refresh();
              },
              (error) => {
                setDeleted(null);
                stale(error);
              },
            )
          }
        />
      )}
    </div>
  );
}
