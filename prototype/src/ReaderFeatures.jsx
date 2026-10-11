import { useEffect, useMemo, useRef, useState } from "react";

export const NOTE_COLORS = { yellow: "#d4a832", green: "#52a67c", blue: "#668bd3", pink: "#ca7199" };
export const NOTE_COLOR_NAMES = { yellow: "黄色", green: "绿色", blue: "蓝色", pink: "粉色" };
export const TYPE_NAMES = { "": "未指定", novel: "小说", article: "文章", reference: "资料" };
export const STATUS_NAMES = { unread: "未读", reading: "阅读中", read: "已读" };

export function ActivityReporter({ features, surface, sessionId, visible }) {
  const sequence = useRef(0);
  const state = useRef({ sessionId, visible });
  state.current = { sessionId, visible };
  useEffect(() => {
    if (!features) return;
    const input = (event) => { if (event.isTrusted) sequence.current += 1; };
    const report = () => features.invoke({ action: "activity", surface, ...state.current, inputSequence: sequence.current }).catch(() => {});
    const events = ["pointerdown", "keydown", "wheel", "pointerup"];
    events.forEach((name) => window.addEventListener(name, input, { passive: true }));
    report();
    const timer = setInterval(report, 1000);
    return () => { clearInterval(timer); events.forEach((name) => window.removeEventListener(name, input)); };
  }, [features, surface]);
  return null;
}

export function KokoroPanel({ features, voices, selectedVoice, onSelect }) {
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (!features) return;
    let alive = true;
    const refresh = () => features.invoke({ action: "modelState" }).then((r) => { if (alive) setState(r.data); }).catch((e) => { if (alive) setError(e.message); });
    refresh();
    const timer = setInterval(refresh, 1000);
    return () => { alive = false; clearInterval(timer); };
  }, [features]);
  const action = async (action, extra = {}) => {
    setPending(true); setError("");
    try { const r = await features.invoke({ action, ...extra }); if (action !== "previewVoice") setState(r.data); }
    catch (e) { setError(e.message); }
    finally { setPending(false); }
  };
  const busy = ["downloading", "verifying", "extracting", "loading"].includes(state?.status);
  const labels = { missing: "未安装", downloading: "正在下载", verifying: "正在校验", extracting: "正在解压", loading: "正在加载", ready: "已就绪 · 完全离线", error: "安装失败", cancelled: "已取消" };
  return <section className="settings-section kokoro-panel"><h3>免费离线音色包</h3><p>Kokoro v1.0 INT8 · 一次下载约132.3 MB，升级保留模型。</p>
    <p role="status">{labels[state?.status] || "正在读取模型状态…"}{state?.installedBytes > 0 ? ` · 模型占用 ${(state.installedBytes / 1048576).toFixed(1)} MiB` : ""}</p>
    {busy ? <><progress max="100" value={state.progressPercent || 0} /><p>{(state.downloadedBytes / 1048576).toFixed(1)} / {(state.totalBytes / 1048576).toFixed(1)} MiB</p></> : null}
    <p className="settings-hint model-directory">{state?.directory}</p>
    {state?.message ? <p className="settings-hint">{state.message}</p> : null}
    {state?.playback?.purpose === "preview" ? <p className="settings-hint" role="status">{state.playback.phase === "speaking" ? "正在试听" : "正在生成试听音频…"} · {voices.find((voice) => voice.id === state.playback.requestedVoiceId)?.label || "离线音色"}</p> : null}
    {error ? <p className="reader-side-error" role="alert">{error}</p> : null}
    <div className="feature-actions"><button className="primary-button" disabled={!features || pending || state?.status === "ready"} onClick={() => action(busy ? "modelCancel" : state?.status === "error" ? "modelRetry" : "modelDownload")}>{busy ? "取消下载 / 安装" : state?.status === "error" ? "重试下载" : state?.status === "ready" ? "模型已安装" : "下载模型"}</button><button className="secondary-button" disabled={busy || pending || !features} onClick={() => action("modelImport")}>导入模型包</button><button className="secondary-button" disabled={busy || pending || !features} onClick={() => action("modelDirectory")}>选择目录</button></div>
    <div className="kokoro-voices">{voices.map((voice) => <div key={voice.id}><button className={selectedVoice === voice.id ? "selected" : ""} disabled={!voice.available} onClick={() => onSelect({ ttsVoiceId: voice.id })}>{voice.label.replace(" · Kokoro离线", "")}</button><button disabled={!voice.available || pending} aria-label={`试听${voice.label}`} onClick={() => action("previewVoice", { voiceId: voice.id })}>试听</button></div>)}</div>
    <p className="settings-hint">试听会暂停书籍朗读，不改变默认音色或进度；结束后可手动继续。</p>
  </section>;
}

const EMPTY_STATS = { today: {}, total: {}, days: [] };
const timeText = (ms = 0) => `${Math.floor(ms / 3600000)}小时${Math.floor(ms / 60000) % 60}分钟`;
export function StatisticsView({ features }) {
  const [stats, setStats] = useState(EMPTY_STATS);
  const [metric, setMetric] = useState("totalMs");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!features) return;
    let alive = true;
    const refresh = () => features.invoke({ action: "statistics" }).then((r) => { if (alive) setStats(r.data); }).catch((e) => { if (alive) setError(e.message); });
    refresh(); const timer = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, [features]);
  const days = useMemo(() => {
    const byDate = new Map(stats.days.map((x) => [x.date, x]));
    return Array.from({ length: 365 }, (_, index) => {
      const date = new Date(); date.setHours(12, 0, 0, 0); date.setDate(date.getDate() - (364 - index));
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      return { date: key, value: byDate.get(key)?.[metric] || 0 };
    });
  }, [stats.days, metric]);
  return <section className="library-page statistics-page"><div className="library-heading"><div><p className="eyebrow">我的阅读</p><h1>阅读与听书统计</h1><p className="subtle">从启用统计开始记录，数据只保存在本地。</p></div></div>
    {error ? <p role="alert" className="library-error">{error}</p> : null}
    <div className="statistics-cards">{[["totalMs", "总时长"], ["readingMs", "阅读"], ["listeningMs", "听书"]].map(([key, name]) => <section className="settings-section" key={key}><h3>{name}</h3><strong>{timeText(stats.today[key])}</strong><p>今日</p><p>累计 {timeText(stats.total[key])}</p></section>)}</div>
    <section className="settings-section"><div className="section-title"><h2>过去一年</h2><select aria-label="热力图统计口径" value={metric} onChange={(e) => setMetric(e.target.value)}><option value="totalMs">总时长</option><option value="readingMs">阅读</option><option value="listeningMs">听书</option></select></div><div className="reading-heatmap">{days.map((day) => <button key={day.date} className={`heatmap-day level-${day.value === 0 ? 0 : day.value < 900000 ? 1 : day.value < 1800000 ? 2 : day.value < 3600000 ? 3 : 4}`} title={`${day.date}：${timeText(day.value)}`} aria-label={`${day.date}：${timeText(day.value)}`} />)}</div><p className="settings-hint">阅读和听书重叠时分别记录，总时长只计算一次。5分钟无操作停止阅读计时；后台实际播放仍计听书。</p></section>
  </section>;
}

export function NoteEditor({ value, onSave, onClose }) {
  const [note, setNote] = useState(value.note || "");
  const [color, setColor] = useState(value.color || "yellow");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  return <div className="modal-backdrop"><div className="paste-modal note-modal" role="dialog" aria-modal="true" aria-label="编辑划线笔记"><div className="modal-header"><h2>{value.id ? "编辑笔记" : "添加划线笔记"}</h2><button className="secondary-button" onClick={onClose}>关闭</button></div><blockquote>{value.text}</blockquote>{value.kind === "bookmark" ? <p className="settings-hint">普通书签保留原有定位，此处编辑备注。</p> : <div className="note-colors">{Object.entries(NOTE_COLORS).map(([key, hex]) => <button key={key} aria-label={`${NOTE_COLOR_NAMES[key]}划线`} aria-pressed={color === key} style={{ background: hex }} onClick={() => setColor(key)} />)}</div>}<label className="settings-field">备注<textarea autoFocus maxLength={10000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="写下你的想法（可留空）" /></label>{error ? <p role="alert">{error}</p> : null}<button className="primary-button" disabled={pending} onClick={async () => { setPending(true); try { await onSave({ ...value, note, color }); onClose(); } catch (e) { setError(e.message); } finally { setPending(false); } }}>保存笔记</button></div></div>;
}

export function ShelfFilters({ filters, onChange, taxonomy }) {
  return <div className="shelf-filters"><select aria-label="内容类型" value={filters.type} onChange={(e) => onChange({ ...filters, type: e.target.value })}><option value="all">全部类型</option>{Object.entries(TYPE_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select><select aria-label="书架分类" value={filters.category} onChange={(e) => onChange({ ...filters, category: e.target.value })}><option value="all">全部分类</option><option value="">未分类</option>{taxonomy.categories.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select><select aria-label="阅读状态" value={filters.status} onChange={(e) => onChange({ ...filters, status: e.target.value })}><option value="all">全部状态</option>{Object.entries(STATUS_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select><div className="shelf-tags" role="group" aria-label="标签筛选">{taxonomy.tags.map((x) => <button key={x.id} className={filters.tags.includes(x.id) ? "selected" : ""} onClick={() => onChange({ ...filters, tags: filters.tags.includes(x.id) ? filters.tags.filter((id) => id !== x.id) : [...filters.tags, x.id] })}>{x.name}</button>)}</div><button className="secondary-button" onClick={() => onChange({ type: "all", category: "all", status: "all", tags: [] })}>清空筛选</button></div>;
}

export function BookOrganizer({ book, taxonomy, features, onUpdated, onClose }) {
  const [patch, setPatch] = useState({ contentType: book.contentType || "", categoryId: book.categoryId || "", tagIds: book.tagIds || [], readingStatus: book.readingStatus || "unread", statusMode: book.statusMode || "auto" });
  const [terms, setTerms] = useState(taxonomy);
  const [kind, setKind] = useState("categories");
  const [name, setName] = useState("");
  const [termId, setTermId] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const action = async (request) => { setPending(true); setError(""); try { const r = await features.invoke({ action: "organizationUpdate", request }); setTerms(r.data); onUpdated(); return true; } catch (e) { setError(e.message); return false; } finally { setPending(false); } };
  return <div className="modal-backdrop"><div className="paste-modal organizer-modal" role="dialog" aria-modal="true" aria-label="编辑书架信息"><div className="modal-header"><h2>{book.title}</h2><button className="secondary-button" onClick={onClose}>关闭</button></div><label className="settings-field">内容类型<select value={patch.contentType} onChange={(e) => setPatch({ ...patch, contentType: e.target.value })}>{Object.entries(TYPE_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><label className="settings-field">分类<select value={patch.categoryId} onChange={(e) => setPatch({ ...patch, categoryId: e.target.value })}><option value="">未分类</option>{terms.categories.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label><div className="shelf-tags">{terms.tags.map((x) => <label key={x.id}><input type="checkbox" checked={patch.tagIds.includes(x.id)} onChange={(e) => setPatch({ ...patch, tagIds: e.target.checked ? [...patch.tagIds, x.id] : patch.tagIds.filter((id) => id !== x.id) })} />{x.name}</label>)}</div><label className="settings-field">阅读状态<select value={patch.readingStatus} onChange={(e) => setPatch({ ...patch, readingStatus: e.target.value, statusMode: "manual" })}>{Object.entries(STATUS_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><label className="confirmation-row"><input type="checkbox" checked={patch.statusMode === "auto"} onChange={(e) => setPatch({ ...patch, statusMode: e.target.checked ? "auto" : "manual" })} />自动判断状态（进度100%即已读）</label><button className="primary-button" disabled={pending} onClick={async () => { if (await action({ action: "book", bookId: book.id, patch })) onClose(); }}>保存书架信息</button><section className="settings-section"><h3>管理分类与标签</h3><div className="feature-actions"><select aria-label="管理类型" value={kind} onChange={(e) => { setKind(e.target.value); setTermId(""); setConfirmDelete(false); }}><option value="categories">分类</option><option value="tags">标签</option></select><select aria-label="管理条目" value={termId} onChange={(e) => { setTermId(e.target.value); setConfirmDelete(false); setName(terms[kind].find((x) => x.id === e.target.value)?.name || ""); }}><option value="">新建条目</option>{terms[kind].filter((x) => !x.builtin).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select><input aria-label="分类或标签名称" maxLength={50} value={name} onChange={(e) => setName(e.target.value)} /></div><div className="feature-actions"><button className="secondary-button" disabled={pending || !name.trim()} onClick={() => action({ action: termId ? "rename" : "create", kind, id: termId, name })}>{termId ? "重命名" : "新增"}</button>{termId ? <button className="secondary-button" disabled={pending} onClick={async () => { if (!confirmDelete) { setConfirmDelete(true); return; } if (await action({ action: "delete", kind, id: termId })) { if (kind === "categories" && patch.categoryId === termId) setPatch({ ...patch, categoryId: "" }); if (kind === "tags") setPatch({ ...patch, tagIds: patch.tagIds.filter((x) => x !== termId) }); setTermId(""); setName(""); setConfirmDelete(false); } }}>{confirmDelete ? "确认删除（仅解除归属）" : "删除条目"}</button> : null}</div></section>{error ? <p className="reader-side-error" role="alert">{error}</p> : null}</div></div>;
}
