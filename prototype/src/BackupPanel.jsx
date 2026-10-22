import { useEffect, useRef, useState } from "react";

const formatBytes = (bytes = 0) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GiB` : `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
const replacementLabel = (name) => ({ "library.json": "书架、进度、笔记、分类标签及设置", cache: "正文与源文件副本", tts_cache: "音频缓存", models: "本地模型", "kokoro-model.json": "模型选择", "offline-jobs-v1.json": "离线章节任务", "offline-audio-refs-v1.json": "保留章节引用", "reading_stats.sqlite3": "阅读与听书统计" })[name] || name;

export default function BackupPanel({ features, onRestored = () => window.location.reload() }) {
  const [includeAudio, setIncludeAudio] = useState(false);
  const [includeModels, setIncludeModels] = useState(false);
  const [inventory, setInventory] = useState(null);
  const [job, setJob] = useState(null);
  const [preview, setPreview] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const processed = useRef("");
  const alive = useRef(true);
  const busy = pending || job?.status === "running";

  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!features || job?.status !== "running") return;
    let active = true;
    let querying = false;
    const refresh = async () => {
      if (querying) return;
      querying = true;
      try { const response = await features.invoke({ action: "backupJob", jobId: job.jobId }); if (active) setJob(response.data); }
      catch (caught) { if (active) setError(caught.message); }
      finally { querying = false; }
    };
    const timer = setInterval(refresh, 400);
    return () => { active = false; clearInterval(timer); };
  }, [features, job?.jobId, job?.status]);

  useEffect(() => {
    if (!job || job.status === "running" || processed.current === job.jobId) return;
    processed.current = job.jobId;
    if (job.error) { setError(job.error.message); return; }
    if (job.status !== "completed") return;
    if (job.kind === "inventory") setInventory(job.result);
    else if (job.kind === "inspect") { setPreview({ ...job.result, jobId: job.jobId }); setConfirmed(false); }
    else if (job.kind === "create") setMessage(`${job.result.complete ? "备份已保存" : "备份已保存，部分源文件或正文缺失"}：${job.result.path}`);
    else if (job.kind === "restore") { setMessage("恢复完成，正在重新载入书架。"); onRestored(job.result); }
  }, [job, onRestored]);

  const start = async (action, extra = {}) => {
    if (!features || busy) return;
    setPending(true); setError(""); setMessage("");
    try {
      const response = await features.invoke({ action, includeAudio, includeModels, ...extra });
      if (!alive.current) return;
      if (response.data.cancelled) setMessage("已取消选择文件。");
      else setJob(response.data);
    } catch (caught) { if (alive.current) setError(caught.message); }
    finally { if (alive.current) setPending(false); }
  };

  return <section className="settings-section backup-panel">
    <h3>备份与恢复</h3>
    <p className="settings-hint">备份书架、正文和源文件副本、进度、笔记、分类标签、收藏及阅读统计。恢复完整快照会替换当前数据，原始外部文件保持原样。</p>
    <div className="feature-actions">
      <label className="confirmation-row"><input type="checkbox" checked={includeAudio} disabled={busy} onChange={(e) => { setIncludeAudio(e.target.checked); setInventory(null); }} />包含音频缓存</label>
      <label className="confirmation-row"><input type="checkbox" checked={includeModels} disabled={busy} onChange={(e) => { setIncludeModels(e.target.checked); setInventory(null); }} />包含已安装模型</label>
    </div>
    <div className="feature-actions">
      <button className="secondary-button" disabled={!features || busy} onClick={() => start("backupInventory")}>估算备份大小</button>
      <button className="primary-button" disabled={!features || busy || !inventory} onClick={() => start("backupCreate")}>选择位置并备份</button>
      <button className="secondary-button" disabled={!features || busy} onClick={() => start("backupInspect")}>选择备份并校验</button>
      {job?.status === "running" ? <button className="secondary-button" onClick={async () => { try { setJob((await features.invoke({ action: "backupCancel", jobId: job.jobId })).data); } catch (caught) { setError(caught.message); } }}>取消任务</button> : null}
    </div>
    {inventory ? <p role="status">预计 {formatBytes(inventory.estimatedBytes)} · {inventory.bookCount} 本书 · {inventory.noteCount} 条笔记 · {inventory.fileCount} 个文件{inventory.missing.length ? ` · ${inventory.missing.length} 项缺失` : ""}</p> : <p className="settings-hint">先估算大小，再选择保存位置。音频与模型可能占用较多磁盘空间。</p>}
    {busy ? <p role="status">{({ inventory: "正在盘点备份内容…", create: "正在生成并校验备份…", inspect: "正在校验备份文件…", restore: "正在恢复，请等待完成…" })[job?.kind] || "正在处理…"}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {error ? <p className="reader-side-error" role="alert">{error}</p> : null}
    {preview ? <section className="settings-section" aria-label="恢复预览">
      <h3>恢复预览</h3>
      <p>{preview.bookCount} 本书 · {preview.noteCount} 条笔记 · {formatBytes(preview.bytes)}</p>
      <p>统计时间：{preview.statisticsRange?.filter(Boolean).join(" 至 ") || "无统计记录"}</p>
      <p className="model-directory">目标位置：{preview.targetRoot}</p>
      <p className="settings-hint">将替换：{preview.replaceNames.map(replacementLabel).join("、")}。恢复前会保留当前数据的回滚快照（预计 {formatBytes(preview.rollbackEstimatedBytes)}）；旧的自定义缓存目录与外部源文件保持原样。</p>
      {preview.missing.length ? <div role="status"><p>该备份有 {preview.missing.length} 项缺失：</p><ul>{preview.missing.slice(0, 20).map((item, index) => <li key={`${item.bookId}-${item.kind}-${index}`}>{item.bookId}：{item.message}</li>)}</ul>{preview.missing.length > 20 ? <p>其余 {preview.missing.length - 20} 项也将保留在恢复结果中。</p> : null}</div> : null}
      <label className="confirmation-row"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)} />我已核对目标位置，确认用此快照替换当前书架、正文、笔记和统计。</label>
      <div className="feature-actions"><button className="primary-button" disabled={busy || !confirmed} onClick={() => start("backupRestore", { previewId: preview.previewId })}>确认恢复</button><button className="secondary-button" disabled={busy} onClick={async () => { try { await features.invoke({ action: "backupCancel", jobId: preview.jobId }); setPreview(null); setConfirmed(false); } catch (caught) { setError(caught.message); } }}>取消恢复</button></div>
    </section> : null}
  </section>;
}
