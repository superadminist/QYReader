import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";
import { FolderOpen, Trash } from "@phosphor-icons/react";

export default function BookContextMenu({ ref, onOrganize, onReveal, onRemove }) {
  const [menu, setMenu] = useState(null);
  const menuRef = useRef(null);
  const triggerRef = useRef(null);
  const menuSizeRef = useRef({ width: 230, height: 130 });
  const open = menu?.open === true;
  const close = useCallback(() => {
    setMenu((current) => current?.open ? { ...current, open: false } : current);
  }, []);

  useImperativeHandle(ref, () => ({
    show(event, book) {
      event.preventDefault();
      event.stopPropagation();
      const trigger = event.currentTarget;
      const keyboard = event.type === "click" && event.detail === 0;
      const anchor = keyboard ? trigger.getBoundingClientRect() : null;
      const { width, height } = menuSizeRef.current;
      triggerRef.current = keyboard ? trigger : null;
      setMenu({
        open: true,
        book,
        keyboard,
        x: Math.max(8, Math.min(anchor?.left ?? event.clientX, window.innerWidth - Math.max(230, width))),
        y: Math.max(8, Math.min(anchor?.bottom ?? event.clientY, window.innerHeight - Math.max(122, height))),
      });
    },
    close,
  }), [close]);

  useLayoutEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      const size = entry.borderBoxSize[0];
      menuSizeRef.current = { width: Math.ceil(size.inlineSize), height: Math.ceil(size.blockSize) };
    });
    observer.observe(menuRef.current, { box: "border-box" });
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    if (menu?.open && menu.keyboard) menuRef.current.firstElementChild.focus({ preventScroll: true });
  }, [menu]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== "Escape") return;
      close();
      if (menuRef.current.contains(document.activeElement)) {
        triggerRef.current?.focus({ preventScroll: true });
      }
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [close, open]);

  const run = (action) => {
    if (!open) return;
    close();
    action(menu.book);
  };
  const canReveal = menu?.book.canRevealSource === true;

  return (
    <div
      ref={menuRef}
      className="book-context-menu"
      role="menu"
      data-open={open}
      inert={!open}
      style={menu ? { left: menu.x, top: menu.y } : undefined}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <button role="menuitem" onClick={() => run(onOrganize)}>分类、标签与阅读状态</button>
      <button
        role="menuitem"
        disabled={!canReveal}
        title={canReveal ? "在文件资源管理器中选中原文件" : "此内容没有可定位的源文件"}
        onClick={() => { if (canReveal) run(onReveal); }}
      >
        <FolderOpen /> 打开源文件位置
      </button>
      <div className="menu-separator" role="separator" />
      <button className="destructive" role="menuitem" onClick={() => run(onRemove)}>
        <Trash /> 从内容库移除
      </button>
    </div>
  );
}
