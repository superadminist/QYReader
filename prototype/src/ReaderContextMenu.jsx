import { useEffect, useRef, useState } from "react";
import * as ContextMenu from "@radix-ui/react-context-menu";
import { BookmarkSimple, CaretRight, Check, Copy, CornersOut, Crosshair, GearSix, Highlighter, NotePencil, Play, SidebarSimple, Trash } from "@phosphor-icons/react";
import { NOTE_COLORS, NOTE_COLOR_NAMES } from "./ReaderFeatures.jsx";
import { readerContextTarget } from "./readerContext.js";

function MenuAction({ icon: Icon, children, onSelect, disabled, destructive }) {
  return <ContextMenu.Item className={`reader-menu-item${destructive ? " destructive" : ""}`} disabled={disabled} onSelect={onSelect}><Icon aria-hidden="true" /><span>{children}</span></ContextMenu.Item>;
}

export default function ReaderContextMenu({ children, resetKey, chapterIndex, annotations, canOpen, onPrepare, onRead, onBookmark, onCopy, onSave, onEdit, onRemove, onLocate, canLocate, playbackPending, directoryVisible, onToggleDirectory, onSettings, floatingAvailable, onFloating }) {
  const [context, setContext] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { setOpen(false); }, [resetKey]);
  const busyRef = useRef(false);
  const triggerRef = useRef(null);
  const target = context?.target;
  const hasText = target && target.kind !== "blank";
  const note = target?.kind === "annotation";
  const selected = target?.kind === "selection";
  const capture = (event) => {
    if (event.target.closest("input, textarea, select, [contenteditable=true]")) { event.stopPropagation(); return; }
    if (event.target.closest("button")) { event.preventDefault(); return; }
    if (busyRef.current || !canOpen()) { event.preventDefault(); return; }
    const target = readerContextTarget(event.currentTarget, event, chapterIndex, annotations);
    triggerRef.current = target.triggerElement || event.currentTarget;
    setContext({ target, container: event.currentTarget.closest(".prototype-stage") });
    onPrepare();
  };
  const run = async (action) => {
    if (busyRef.current) return;
    busyRef.current = true;
    try { await action(); } finally { busyRef.current = false; }
  };
  const colorMenu = <ContextMenu.Sub>
    <ContextMenu.SubTrigger className="reader-menu-item"><Highlighter aria-hidden="true" /><span>{note ? "更换划线颜色" : "划线"}</span><CaretRight className="reader-menu-trailing" aria-hidden="true" /></ContextMenu.SubTrigger>
    <ContextMenu.Portal container={context?.container}><ContextMenu.SubContent className="reader-context-menu reader-color-menu" sideOffset={5} collisionPadding={12} aria-label="划线颜色">{Object.entries(NOTE_COLORS).map(([color, hex]) => <ContextMenu.Item key={color} className="reader-menu-item" onSelect={() => run(() => onSave({ ...target, kind: "annotation", color, note: target.note || "" }))}><span className="reader-menu-color" style={{ background: hex }} /><span>{NOTE_COLOR_NAMES[color]}</span>{note && target.color === color ? <Check className="reader-menu-trailing" aria-hidden="true" /> : null}</ContextMenu.Item>)}</ContextMenu.SubContent></ContextMenu.Portal>
  </ContextMenu.Sub>;

  return <ContextMenu.Root modal={false} open={open} onOpenChange={setOpen}>
    <ContextMenu.Trigger asChild onContextMenuCapture={capture} onKeyDown={(event) => {
      if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
      event.preventDefault();
      event.stopPropagation();
      const selectedRange = window.getSelection()?.rangeCount ? window.getSelection().getRangeAt(0) : null;
      const hasSelection = selectedRange && !selectedRange.collapsed && event.currentTarget.contains(selectedRange.startContainer);
      const selectedElement = hasSelection ? selectedRange.startContainer.nodeType === 1 ? selectedRange.startContainer : selectedRange.startContainer.parentElement : null;
      const trigger = selectedElement || event.target;
      const rect = hasSelection ? selectedRange.getClientRects()[0] || trigger.getBoundingClientRect() : trigger.getBoundingClientRect();
      trigger.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2, clientX: rect.left + Math.min(20, rect.width / 2), clientY: rect.top + Math.min(20, rect.height / 2) }));
    }}>{children}</ContextMenu.Trigger>
    <ContextMenu.Portal container={context?.container}>
      <ContextMenu.Content className="reader-context-menu" collisionPadding={12} loop aria-label="阅读操作" onContextMenu={(event) => event.preventDefault()} onKeyDown={(event) => event.stopPropagation()} onCloseAutoFocus={(event) => { event.preventDefault(); if (document.activeElement === document.body) triggerRef.current?.focus({ preventScroll: true }); }}>
        <ContextMenu.Label className="reader-menu-label">{note ? "划线与笔记" : selected ? "选中文字" : hasText ? "段落操作" : "阅读操作"}</ContextMenu.Label>
        {hasText ? <>
          <MenuAction icon={Play} disabled={playbackPending} onSelect={() => onRead(target)}>{selected ? "从选中处朗读" : note ? "从划线处朗读" : "从这里朗读"}</MenuAction>
          {selected || note ? <MenuAction icon={Copy} onSelect={() => run(() => onCopy(target.text))}>复制{selected ? "选中文字" : "划线文字"}</MenuAction> : <MenuAction icon={BookmarkSimple} onSelect={() => run(() => onBookmark(target))}>添加书签</MenuAction>}
          {selected || note ? <>
            <ContextMenu.Separator className="reader-menu-separator" />
            {colorMenu}
            <MenuAction icon={NotePencil} onSelect={() => requestAnimationFrame(() => onEdit({ ...target, initialEditing: true, keyboardOpened: true }))}>{note ? "编辑笔记" : "写笔记"}</MenuAction>
            {note ? <MenuAction icon={Trash} destructive onSelect={() => run(() => onRemove(target.id))}>删除划线与笔记</MenuAction> : null}
          </> : null}
          <ContextMenu.Separator className="reader-menu-separator" />
        </> : null}
        <MenuAction icon={Crosshair} disabled={!canLocate} onSelect={onLocate}>回到当前朗读位置</MenuAction>
        {!hasText ? <>
          <ContextMenu.Separator className="reader-menu-separator" />
          <MenuAction icon={SidebarSimple} onSelect={onToggleDirectory}>{directoryVisible ? "隐藏目录" : "显示目录"}</MenuAction>
          <MenuAction icon={GearSix} onSelect={onSettings}>阅读设置</MenuAction>
          {floatingAvailable ? <MenuAction icon={CornersOut} onSelect={onFloating}>进入悬浮阅读</MenuAction> : null}
        </> : null}
      </ContextMenu.Content>
    </ContextMenu.Portal>
  </ContextMenu.Root>;
}
