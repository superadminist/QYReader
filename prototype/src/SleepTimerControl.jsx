import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export function sleepTimerLabel(timer) {
  if (timer?.mode === "chapter") return "本章结束停止";
  if (timer?.mode === "minutes") { const seconds = Math.ceil(timer.remainingMs / 1000); return `剩余 ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`; }
  return ({ expired: "定时已到", chapterEnd: "本章已读完", chapterChanged: "跳章已取消定时", bookChanged: "切书已取消定时" })[timer?.endReason] || "睡眠定时";
}

export default function SleepTimerControl({ timer, features }) {
  const [custom, setCustom] = useState(false);
  const [dialogTheme, setDialogTheme] = useState({});
  const controlRef = useRef(null);
  const selectRef = useRef(null);
  const returnFocus = useRef(false);
  const closeCustom = () => { if (!pending) { returnFocus.current = true; setCustom(false); } };
  const openCustom = () => {
    const style = getComputedStyle(controlRef.current);
    setDialogTheme(Object.fromEntries(["--ui-panel", "--ui-raised", "--ui-text", "--ui-muted", "--ui-border", "--ui-accent"].map((key) => [key, style.getPropertyValue(key)]).filter(([, value]) => value.trim())));
    setCustom(true);
  };
  const [minutes, setMinutes] = useState(30);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setError(""); }, [timer?.version]);
  useEffect(() => {
    if (!custom && !pending && returnFocus.current) { returnFocus.current = false; selectRef.current?.focus(); }
  }, [custom, pending]);
  const apply = async (mode, value) => {
    if (pending) return;
    setPending(true); setError("");
    try { await features.invoke({ action: "sleepTimer", mode, ...(mode === "minutes" ? { minutes: value } : {}) }); returnFocus.current = true; setCustom(false); }
    catch (e) { setError(e.message); }
    finally { setPending(false); }
  };
  return <div className="sleep-timer-control" ref={controlRef}>
    <select ref={selectRef} aria-label="睡眠定时" title={sleepTimerLabel(timer)} value="" disabled={!features || pending} onChange={(e) => { const value = e.target.value; if (value === "custom") openCustom(); else apply(value === "chapter" || value === "off" ? value : "minutes", Number(value)); }}>
      <option value="" disabled>{sleepTimerLabel(timer)}</option>
      {[15, 30, 60].map((n) => <option value={n} key={n}>{n} 分钟</option>)}
      <option value="custom">自定义分钟</option><option value="chapter">读完本章</option><option value="off">取消定时</option>
    </select>
    {custom ? createPortal(<div className="modal-backdrop sleep-timer-backdrop" style={dialogTheme} onKeyDown={(e) => {
      if (e.key === "Escape") { e.stopPropagation(); closeCustom(); }
      if (e.key === "Tab") {
        const targets = [...e.currentTarget.querySelectorAll("input, button")].filter((el) => !el.disabled);
        const first = targets[0], last = targets.at(-1);
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    }}><div className="paste-modal sleep-timer-modal" role="dialog" aria-modal="true" aria-label="自定义睡眠定时">
      <h3>自定义睡眠定时</h3><p className="settings-hint">暂停朗读也会继续计时。</p>
      <form onSubmit={(e) => { e.preventDefault(); apply("minutes", Number(minutes)); }}>
        <label className="settings-field">分钟（1–720）<input autoFocus aria-label="自定义定时分钟" type="number" min="1" max="720" step="1" required value={minutes} disabled={pending} onChange={(e) => setMinutes(e.target.value)} /></label>
        {error ? <p role="alert">{error}</p> : null}
        <div className="feature-actions"><button className="primary-button" disabled={pending}>确定</button><button className="secondary-button" type="button" disabled={pending} onClick={closeCustom}>取消</button></div>
      </form>
    </div></div>, document.body) : null}
    {error && !custom ? <small role="alert">{error}</small> : null}
  </div>;
}
