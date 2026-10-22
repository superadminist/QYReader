import { useEffect, useMemo, useRef, useState } from "react";
const ENGINE_NAMES = { edge: "Edge 在线", kokoro: "Kokoro 离线", sapi: "系统离线" };
export default function VoiceCenter({ features, selectedVoice, onSelect }) {
  const [state, setState] = useState({ voices: [], favorites: [], playback: null });
  const [query, setQuery] = useState("");
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const revision = useRef(0);
  const mutating = useRef(false);
  useEffect(() => {
    if (!features) return;
    let active = true;
    const refresh = () => {
      if (mutating.current) return;
      const version = revision.current;
      features.invoke({ action: "voiceCenter" }).then((r) => { if (active && version === revision.current) setState(r.data); }).catch((e) => { if (active && version === revision.current) setError(e.message); });
    };
    refresh(); const timer = setInterval(refresh, 1000);
    return () => { active = false; clearInterval(timer); };
  }, [features]);
  const action = async (action, extra = {}) => {
    if (mutating.current) return;
    mutating.current = true; revision.current += 1;
    setPending(true); setError("");
    try { const r = await features.invoke({ action, ...extra }); if (action === "voiceFavorite") setState(r.data); }
    catch (e) { setError(e.message); }
    finally { mutating.current = false; setPending(false); }
  };
  const visible = useMemo(() => state.voices.filter((v) => (!onlyFavorites || state.favorites.includes(v.id)) && `${v.label} ${v.id} ${v.backend} ${ENGINE_NAMES[v.backend]}`.toLowerCase().includes(query.trim().toLowerCase())), [state.voices, state.favorites, query, onlyFavorites]);
  const preview = state.playback?.purpose === "preview";
  return <section className="settings-section voice-center"><h3>音色中心</h3>
    <div className="feature-actions"><input aria-label="搜索音色" type="search" placeholder="搜索中文名称、引擎或音色 ID" value={query} onChange={(e) => setQuery(e.target.value)} /><label><input type="checkbox" checked={onlyFavorites} onChange={(e) => setOnlyFavorites(e.target.checked)} />仅收藏</label></div>
    {preview ? <p role="status">{state.playback.phase === "speaking" ? "正在试听" : "准备试听…"}<button className="secondary-button" disabled={pending} onClick={() => action("cancelPreview")}>取消试听</button></p> : null}
    {Object.entries(ENGINE_NAMES).map(([engine, label]) => <div className="voice-group" key={engine}><h4>{label}</h4>{visible.filter((v) => v.backend === engine).map((v) => <div className="voice-row" key={v.id}>
      <button className={selectedVoice === v.id ? "selected" : ""} disabled={!v.available} title={v.unavailableReason || v.id} onClick={() => onSelect({ ttsVoiceId: v.id })}>{v.label}<small>{v.statusLabel}{selectedVoice === v.id ? " · 当前朗读" : ""}</small></button>
      <button className="secondary-button" aria-label={`收藏${v.label}`} aria-pressed={state.favorites.includes(v.id)} disabled={pending} onClick={() => action("voiceFavorite", { voiceId: v.id, favorite: !state.favorites.includes(v.id) })}>{state.favorites.includes(v.id) ? "★" : "☆"}</button>
      <button className="secondary-button" disabled={!v.available || pending} title={v.unavailableReason} onClick={() => action("previewVoice", { voiceId: v.id })}>试听</button>
      {v.unavailableReason ? <small>{v.unavailableReason}</small> : null}
    </div>)}</div>)}
    {visible.length === 0 ? <p>没有匹配的音色。</p> : null}
    <p className="settings-hint">试听使用相同文案，暂停书籍朗读且不保存音色选择；结束后请手动继续。Edge 需要联网，连接失败会在播放状态中说明。</p>
    {state.playback?.preview?.error ? <p role="alert" className="reader-side-error">{state.playback.preview.error.message}{state.playback.fallbackActive ? " · 当前已使用系统回退音色" : ""}</p> : null}
    {error ? <p role="alert" className="reader-side-error">{error}</p> : null}
  </section>;
}
