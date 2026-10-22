import { useRef, useState } from "react";

const STATUS_LABELS = { unread: "未读", reading: "阅读中", read: "已读", auto: "恢复自动判断" };

export function toggleLibrarySelection(selectedIds, bookId) {
  return selectedIds.includes(bookId) ? selectedIds.filter((id) => id !== bookId) : [...selectedIds, bookId];
}

/** Parent owns selected IDs so filtering and virtualized cards cannot lose them. */
export default function BatchLibraryControls({ selectionMode, onSelectionModeChange, selectedIds, filteredIds, onSelectionChange, taxonomy, features, onUpdated }) {
  const [editing, setEditing] = useState(false);
  const [operation, setOperation] = useState("category");
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const selected = new Set(selectedIds);
  const visibleSelected = filteredIds.filter((id) => selected.has(id)).length;
  const hiddenSelected = selectedIds.length - visibleSelected;
  const terms = operation === "category" ? taxonomy.categories : taxonomy.tags;
  const valid = operation === "category" || Boolean(value);
  const count = selectedIds.length;
  const patch = operation === "category" ? { categoryId: value }
    : operation === "status" ? (value === "auto" ? { statusMode: "auto" } : { readingStatus: value })
    : { [operation === "addTag" ? "addTagIds" : "removeTagIds"]: [value] };
  const apply = async () => {
    if (pendingRef.current || !count || !valid) return;
    const targetIds = [...selectedIds];
    pendingRef.current = true; setPending(true); setError(""); setFeedback("");
    try {
      await features.invoke({ action: "organizationUpdate", request: { action: "batch", bookIds: targetIds, patch } });
      await onUpdated?.();
      setFeedback(`已更新 ${targetIds.length} 项内容。`);
      setEditing(false);
    } catch (e) { setError(e.message || "批量修改失败，已保留选择。" ); }
    finally { pendingRef.current = false; setPending(false); }
  };
  const close = () => { if (!pendingRef.current) { setEditing(false); setError(""); } };
  return <>
    <div className="feature-actions library-batch-controls" role="group" aria-label="书架批量管理">
      <button className="secondary-button" disabled={!features || pending} aria-pressed={selectionMode} onClick={() => { onSelectionModeChange(!selectionMode); setFeedback(""); }}>{selectionMode ? "退出多选" : "批量管理"}</button>
      {selectionMode ? <>
        <span role="status">已选 {count} 项{hiddenSelected > 0 ? `（筛选外 ${hiddenSelected} 项）` : ""}</span>
        <button className="secondary-button" disabled={pending || !filteredIds.length} onClick={() => onSelectionChange([...new Set([...selectedIds, ...filteredIds])])}>全选当前筛选结果（{filteredIds.length}）</button>
        <button className="secondary-button" disabled={pending || !count} onClick={() => onSelectionChange([])}>取消全部选择</button>
        <button className="secondary-button" disabled={pending || !visibleSelected} onClick={() => { const visible = new Set(filteredIds); onSelectionChange(selectedIds.filter((id) => !visible.has(id))); }}>取消当前筛选选择</button>
        <button className="primary-button" disabled={pending || !count} onClick={() => { setEditing(true); setError(""); }}>批量编辑 {count} 项</button>
      </> : null}
      {feedback ? <span role="status">{feedback}</span> : null}
    </div>
    {editing ? <div className="modal-backdrop" onKeyDown={(event) => { if (event.key === "Escape") close(); }}><div className="paste-modal organizer-modal" role="dialog" aria-modal="true" aria-label="批量编辑书架信息">
      <div className="modal-header"><h2>批量编辑 {count} 项内容</h2><button className="secondary-button" disabled={pending} onClick={close}>关闭</button></div>
      <p className="settings-hint">本次修改所有已选内容，包含当前筛选外的 {hiddenSelected} 项。</p>
      <label className="settings-field"><span>修改项目</span><select autoFocus disabled={pending} value={operation} onChange={(event) => { setOperation(event.target.value); setValue(""); }}><option value="category">设置 / 清除分类</option><option value="addTag">添加标签</option><option value="removeTag">移除标签</option><option value="status">设置阅读状态</option></select></label>
      <label className="settings-field"><span>{operation === "status" ? "阅读状态" : operation === "category" ? "分类" : "标签"}</span><select disabled={pending} value={value} onChange={(event) => setValue(event.target.value)}>
        <option value="">{operation === "category" ? "清除分类" : "请选择"}</option>
        {operation === "status" ? Object.entries(STATUS_LABELS).map(([id, name]) => <option key={id} value={id}>{name}</option>) : terms.map((term) => <option key={term.id} value={term.id}>{term.name}</option>)}
      </select></label>
      <p className="settings-hint">{operation === "status" ? "人工设置的状态会保留；选择恢复自动判断后才根据进度更新。" : operation === "addTag" || operation === "removeTag" ? "只添加或移除所选标签，保留其他标签。" : "只更改分类。"}</p>
      {error ? <p className="reader-side-error" role="alert">{error}</p> : null}
      <div className="feature-actions"><button className="primary-button" disabled={pending || !count || !valid} onClick={apply}>{pending ? "正在保存…" : `确认修改 ${count} 项`}</button><button className="secondary-button" disabled={pending} onClick={close}>取消</button></div>
    </div></div> : null}
  </>;
}
