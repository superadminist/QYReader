import { readerPositionAtPoint, readerSelectionFromRange } from "./readerPosition.js";

// Capture offsets and the DOM range before opening a menu moves keyboard focus.
export function readerContextTarget(root, event, chapterIndex, annotations) {
  const element = event.target?.closest ? event.target : event.target?.parentElement;
  const block = element?.closest("[data-reader-block]");
  if (!block || !root.contains(block)) return { kind: "blank" };
  const selection = root.ownerDocument.defaultView.getSelection();
  const range = selection?.rangeCount && !selection.isCollapsed ? selection.getRangeAt(0) : null;
  const withinSelection = range && Array.from(range.getClientRects()).some((rect) => (
    event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom
  ));
  const selected = withinSelection ? readerSelectionFromRange(root, range, chapterIndex) : null;
  if (selected) return { ...selected, kind: "selection", anchorRange: range.cloneRange() };
  const triggerElement = element.closest("[data-annotation-id]");
  const note = annotations.find((item) => item.kind === "annotation" && item.id === triggerElement?.dataset.annotationId);
  if (note) {
    const anchorRange = root.ownerDocument.createRange();
    anchorRange.selectNodeContents(triggerElement);
    return { ...note, kind: "annotation", anchorRange, triggerElement };
  }
  const position = readerPositionAtPoint(root, event.clientX, event.clientY, chapterIndex);
  const anchorRange = root.ownerDocument.createRange();
  anchorRange.selectNodeContents(block);
  const startOffset = Number(block.dataset.startOffset);
  const text = block.textContent || "";
  return { kind: "paragraph", chapterIndex, startOffset, endOffset: startOffset + Array.from(text).length, text, position, anchorRange };
}

export async function copyReaderText(text, documentObject = document) {
  // WebEngine file pages may not expose the async Clipboard API.
  try {
    if (documentObject.defaultView.location.protocol !== "file:" && documentObject.defaultView.navigator.clipboard?.writeText) {
      await documentObject.defaultView.navigator.clipboard.writeText(text);
      return;
    }
  } catch { /* Fall back to a temporary native copy selection. */ }
  const selection = documentObject.defaultView.getSelection();
  const ranges = Array.from({ length: selection?.rangeCount || 0 }, (_, index) => selection.getRangeAt(index).cloneRange());
  const focused = documentObject.activeElement;
  const field = documentObject.createElement("textarea");
  field.value = text;
  field.setAttribute("aria-hidden", "true");
  field.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
  documentObject.body.append(field);
  try {
    field.select();
    if (!documentObject.execCommand("copy")) throw new Error("复制失败，请使用 Ctrl+C 重试。");
  } finally {
    field.remove();
    focused?.focus({ preventScroll: true });
    selection?.removeAllRanges();
    ranges.forEach((range) => { if (range.startContainer.isConnected) selection?.addRange(range); });
  }
}
