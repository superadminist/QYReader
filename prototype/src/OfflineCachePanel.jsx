import { useEffect, useMemo, useState } from "react";

const STATE_NAMES = { queued: "排队中", preparing: "准备中", running: "生成中", paused: "已暂停", cancelled: "已取消", completed: "已完成", error: "失败" };
export function selectedChapterIndices(scope, custom, current, count, total) {
  if (scope === "all") return Array.from({ length: total }, (_, i) => i);
  if (scope === "current") return [current];
  if (scope === "following") {
    if (!Number.isInteger(Number(count)) || Number(count) < 1 || Number(count) > total - current) throw new Error("准备章数超出范围。 ");
    return Array.from({ length: Number(count) }, (_, i) => current + i);
  }
  const selected = new Set();
  if (!custom.trim()) throw new Error("请输入章节编号，如 1,3-5。");
  for (const part of custom.split(/[,，]/)) {
    if (!/^\s*\d+\s*(?:-\s*\d+\s*)?$/.test(part)) throw new Error("章节格式应为 1,3-5。");
    const [start, end = start] = part.trim().split(/\s*-\s*/).map(Number);
    if (start < 1 || end < start || end > total) throw new Error("章节编号超出范围。");
    for (let i = start; i <= end; i++) selected.add(i - 1);
  }
  return [...selected].sort((a, b) => a - b);
}

export default function OfflineCachePanel({ features, book, currentChapterIndex = 0, voices = [], requestedVoiceId = "", rate: initialRate = 200, onClose, onOpenModels }) {
  const [jobs, setJobs] = useState([]);
  const [backend, setBackend] = useState(requestedVoiceId.startsWith("kokoro:") ? "kokoro" : "edge");
  const [voiceId, setVoiceId] = useState(requestedVoiceId);
  const [rate, setRate] = useState(initialRate);
  const [scope, setScope] = useState("current");
  const [custom, setCustom] = useState("");
  const [count, setCount] = useState(3);
  const [pending, setPending] = useState(false);
  const [confirmClean, setConfirmClean] = useState("");
  const [error, setError] = useState("");
  const availableVoices = useMemo(() => voices.filter((voice) => voice.backend === backend), [voices, backend]);
  const selectedVoice = availableVoices.some((voice) => voice.id === voiceId) ? voiceId : availableVoices[0]?.id || "";
  const total = book?.chapters?.length || 0;
  useEffect(() => {
    if (!features) return;
    let active = true;
    const refresh = () => features.invoke({ action: "cacheState" }).then((r) => { if (active) setJobs(r.data.jobs); }).catch((e) => { if (active) setError(e.message); });
    refresh();
    const timer = setInterval(refresh, 1500);
    return () => { active = false; clearInterval(timer); };
  }, [features]);
  const action = async (input) => {
    if (pending) return;
    setPending(true); setError("");
    try {
      await features.invoke(input);
      const r = await features.invoke({ action: "cacheState" });
      setJobs(r.data.jobs); setConfirmClean("");
    } catch (e) { setError(e.message); }
    finally { setPending(false); }
  };
  const start = () => {
    try {
      if (!book?.id || !total) throw new Error("请先打开一本书，再选择要准备的章节。");
      const chapterIndices = selectedChapterIndices(scope, custom, currentChapterIndex, count, total);
      action({ action: "cacheCreate", bookId: book.id, chapterIndices, backend, voiceId: selectedVoice, rate: Number(rate) });
    } catch (e) { setError(e.message); }
  };
  const control = (jobId, command, confirmed = false) => action({ action: "cacheControl", jobId, command, confirmed });
  const content = <div className="offline-cache-panel">
    <div className="modal-header"><h2>准备离线听书</h2>{onClose ? <button className="secondary-button" onClick={onClose}>关闭</button> : null}</div>
    <p className="settings-hint">只准备你选择的章节。当前播放、跳转和试听优先；SAPI仍可实时朗读，不支持预生成。</p>
    {book ? <section className="settings-section"><h3>{book.title}</h3>
      <label className="settings-field">引擎<select aria-label="离线准备引擎" value={backend} onChange={(e) => setBackend(e.target.value)}><option value="edge">Edge · 联网准备</option><option value="kokoro">Kokoro · 本地生成</option></select></label>
      <label className="settings-field">音色<select aria-label="离线准备音色" value={selectedVoice} onChange={(e) => setVoiceId(e.target.value)}>{availableVoices.map((voice) => <option key={voice.id} value={voice.id}>{voice.label}{voice.available === false ? " · 未就绪" : ""}</option>)}</select></label>
      <label className="settings-field">语速<input aria-label="离线准备语速" type="number" min="80" max="400" step="1" value={rate} onChange={(e) => setRate(e.target.value)} /></label>
      <label className="settings-field">章节范围<select aria-label="离线章节范围" value={scope} onChange={(e) => setScope(e.target.value)}><option value="current">当前章 · 第 {currentChapterIndex + 1} 章</option><option value="following">从当前章起后续若干章</option><option value="custom">自选章节编号</option><option value="all">全部 {total} 章（准备整本）</option></select></label>
      {scope === "following" ? <label className="settings-field">准备章数<input type="number" min="1" max={Math.max(1, total - currentChapterIndex)} value={count} onChange={(e) => setCount(e.target.value)} /></label> : null}
      {scope === "custom" ? <label className="settings-field">章节编号<input placeholder="例如 1,3-5" value={custom} onChange={(e) => setCustom(e.target.value)} /></label> : null}
      {backend === "kokoro" ? <p className="settings-hint">首次需要准备，完成后可离线听。保留的章节由你主动清理，不会被临时缓存淘汰。{onOpenModels ? <button className="secondary-button" onClick={onOpenModels}>下载 / 导入模型</button> : null}</p> : null}
      <button className="primary-button" disabled={pending || !selectedVoice || !total} onClick={start}>开始准备所选章节</button>
    </section> : <p className="settings-hint">打开书籍后可选择章节；下方可管理已有任务。</p>}
    {error ? <p className="reader-side-error" role="alert">{error}</p> : null}
    <div aria-live="polite">{jobs.length ? jobs.map((job) => <section className="settings-section" key={job.jobId}>
      <h3>{job.bookTitle || job.bookId} · {job.backend === "kokoro" ? "Kokoro" : "Edge"}</h3>
      <p>{job.voiceId} · 语速 {job.rate}{job.modelId ? ` · ${job.modelId}` : ""}</p>
      <p role="status">{STATE_NAMES[job.state] || job.state} · {job.done} / {job.total} 片段 · {(job.bytes / 1048576).toFixed(1)} MiB{job.verified ? " · 已校验" : " · 待校验"}</p>
      <progress max={Math.max(1, job.total)} value={job.done} />
      {job.message ? <p className="settings-hint">{job.message}</p> : null}
      {job.chapters?.length ? <details><summary>章节进度（{job.chapters.length}章）</summary>{job.chapters.map((chapter) => <p key={chapter.index}>第 {chapter.index + 1} 章：{chapter.done} / {chapter.total}</p>)}</details> : null}
      <div className="feature-actions">
        {["queued", "preparing", "running"].includes(job.state) ? <button className="secondary-button" disabled={pending} onClick={() => control(job.jobId, "pause")}>暂停</button> : <><button className="secondary-button" disabled={pending} onClick={() => control(job.jobId, "resume")}>继续 / 检查并补齐</button><button className="secondary-button" disabled={pending} onClick={() => control(job.jobId, "verify")}>仅校验</button></>}
        <button className="secondary-button" disabled={pending || job.state === "cancelled"} onClick={() => control(job.jobId, "cancel")}>取消任务（保留音频）</button>
        <button className="secondary-button" disabled={pending || ["queued", "preparing", "running"].includes(job.state)} onClick={() => setConfirmClean(job.jobId)}>清理所选缓存</button>
      </div>
      {confirmClean === job.jobId ? <div className="settings-section"><p>清理此任务的 {job.chapterIndices.length} 章音频，约 {(job.bytes / 1048576).toFixed(1)} MiB；共享和占用文件将保留。</p><button className="secondary-button" disabled={pending} onClick={() => control(job.jobId, "clean", true)}>确认清理</button><button className="secondary-button" onClick={() => setConfirmClean("")}>返回</button></div> : null}
    </section>) : <p className="settings-hint">尚无离线章节任务。</p>}</div>
  </div>;
  return onClose ? <div className="modal-backdrop"><div className="paste-modal organizer-modal" role="dialog" aria-modal="true" aria-label="准备离线听书">{content}</div></div> : content;
}
