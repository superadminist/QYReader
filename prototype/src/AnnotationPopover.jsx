import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, NotePencil, Play, Trash, X } from "@phosphor-icons/react";
import { NOTE_COLORS, NOTE_COLOR_NAMES } from "./ReaderFeatures.jsx";
import { annotationPopoverPosition, visibleAnnotationAnchor } from "./annotationPosition.js";

export default function AnnotationPopover({ selection, sheetRef, onSave, onRemove, onRead, onClose, onInteractionLockChange }) {
  const popoverRef = useRef(null);
  const busyRef = useRef(false);
  const keyboardFocusedRef = useRef(false);
  const [position, setPosition] = useState(null);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(selection.note || "");
  const [color, setColor] = useState(selection.color || "yellow");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    onInteractionLockChange(editing || pending);
    return () => onInteractionLockChange(false);
  }, [editing, pending, onInteractionLockChange]);

  useEffect(() => {
    if (position && selection.keyboardOpened && !keyboardFocusedRef.current) {
      popoverRef.current?.querySelector("button")?.focus({ preventScroll: true });
      keyboardFocusedRef.current = true;
    }
  }, [position, selection.keyboardOpened]);

  useLayoutEffect(() => {
    const place = () => {
      const sheet = sheetRef.current;
      const popover = popoverRef.current;
      const range = selection.anchorRange;
      if (!sheet || !popover || !range?.startContainer?.isConnected) { onClose(); return; }
      const rect = sheet.getBoundingClientRect();
      const bounds = { left: Math.max(0, rect.left), top: Math.max(0, rect.top), right: Math.min(window.innerWidth, rect.right), bottom: Math.min(window.innerHeight, rect.bottom) };
      const anchor = visibleAnnotationAnchor(range.getClientRects(), bounds);
      if (!anchor) { if (!busyRef.current && !editing) onClose(); return; }
      const size = popover.getBoundingClientRect();
      setPosition(annotationPopoverPosition(anchor, bounds, size));
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    const observer = new ResizeObserver(place);
    if (popoverRef.current) observer.observe(popoverRef.current);
    if (sheetRef.current) observer.observe(sheetRef.current);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); observer.disconnect(); };
  }, [selection, sheetRef, editing, onClose]);

  useEffect(() => {
    const outside = (event) => {
      if (!popoverRef.current?.contains(event.target) && !busyRef.current && !editing) onClose();
    };
    const escape = (event) => {
      if (event.key === "Escape" && !busyRef.current) { event.preventDefault(); event.stopPropagation(); onClose(true); }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape, true); };
  }, [editing, onClose]);

  const run = async (action) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setPending(true); setError("");
    try { await action(); } catch (e) { setError(e.message || "保存失败，请重试。"); } finally { busyRef.current = false; setPending(false); }
  };
  const save = (chosenColor = color) => run(() => onSave({ ...selection, kind: "annotation", color: chosenColor, note }));

  return <div ref={popoverRef} className={`annotation-popover${editing ? " is-editing" : ""}`} style={{ ...position, visibility: position ? "visible" : "hidden" }} role="dialog" aria-label={selection.id ? "划线笔记" : "选中文字操作"} aria-busy={pending}>
    <div className="annotation-actions" role="toolbar" aria-label="划线与笔记工具">
      <div className="annotation-colors" role="group" aria-label="划线颜色"><span>划线</span>{Object.entries(NOTE_COLORS).map(([key, hex]) => <button type="button" key={key} className="annotation-color" style={{ "--note-color": hex }} title={`${NOTE_COLOR_NAMES[key]}划线`} aria-label={`${selection.id ? "改为" : "添加"}${NOTE_COLOR_NAMES[key]}划线`} aria-pressed={(editing || Boolean(selection.id)) && color === key} disabled={pending} onPointerDown={(event) => event.preventDefault()} onClick={() => { setColor(key); if (!editing) save(key); }}><span>{(editing || selection.id) && color === key ? <Check weight="bold" /> : null}</span></button>)}</div>
      <span className="annotation-divider" aria-hidden="true" />
      <button type="button" className="annotation-action" disabled={pending} onClick={() => setEditing(true)}><NotePencil />{selection.id ? "编辑笔记" : "写笔记"}</button>
      {!editing ? <><span className="annotation-divider" aria-hidden="true" /><button type="button" className="annotation-action" disabled={pending} onPointerDown={(event) => event.preventDefault()} onClick={() => onRead(selection)} title="从选中文字开始朗读"><Play weight="fill" />朗读</button></> : null}
      {selection.id && !editing ? <button type="button" className="annotation-icon danger" title="删除划线和笔记" aria-label="删除划线和笔记" disabled={pending} onClick={() => run(() => onRemove(selection.id))}><Trash /></button> : null}
      <button type="button" className="annotation-icon" title="关闭" aria-label="关闭划线工具" disabled={pending} onClick={() => onClose(true)}><X /></button>
    </div>
    {selection.id && !editing ? <div className="annotation-note-preview">{note || "还没有笔记，点击“编辑笔记”补充想法。"}</div> : null}
    {editing ? <form className="annotation-editor" onSubmit={(event) => { event.preventDefault(); save(); }}>
      <blockquote>{selection.text}</blockquote>
      <textarea aria-label="笔记内容" autoFocus maxLength={10000} value={note} disabled={pending} onChange={(event) => setNote(event.target.value)} placeholder="写下你的想法…" onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); save(); } }} />
      <div className="annotation-editor-footer"><span>Ctrl + Enter 保存</span><button type="button" className="annotation-action" disabled={pending} onClick={() => onClose(true)}>取消</button><button type="submit" className="primary-button" disabled={pending}>{pending ? "正在保存…" : "保存笔记"}</button></div>
    </form> : null}
    {error ? <p className="annotation-error" role="alert">{error}</p> : null}
  </div>;
}
