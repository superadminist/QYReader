function elementForNode(node) {
  if (!node) return null;
  return node.nodeType === 1 ? node : node.parentElement;
}

function readerBlockForNode(root, node) {
  const block = elementForNode(node)?.closest?.("[data-reader-block]");
  return block && root?.contains(block) ? block : null;
}

export function readerPositionFromRange(root, range, chapterIndex) {
  const block = readerBlockForNode(root, range?.startContainer);
  if (!block) return null;

  const blockStart = Number(block.dataset.startOffset);
  if (!Number.isInteger(blockStart) || blockStart < 0) return null;

  const prefixRange = root.ownerDocument.createRange();
  prefixRange.selectNodeContents(block);
  try {
    prefixRange.setEnd(range.startContainer, range.startOffset);
  } catch {
    return null;
  }

  const blockLength = Array.from(block.textContent || "").length;
  const localOffset = Math.min(blockLength, Array.from(prefixRange.toString()).length);
  return {
    kind: "position",
    chapterIndex,
    charOffset: blockStart + localOffset,
  };
}

function rangeAtPoint(documentObject, clientX, clientY) {
  if (typeof documentObject.caretPositionFromPoint === "function") {
    const position = documentObject.caretPositionFromPoint(clientX, clientY);
    if (!position) return null;
    const range = documentObject.createRange();
    range.setStart(position.offsetNode, position.offset);
    range.collapse(true);
    return range;
  }
  if (typeof documentObject.caretRangeFromPoint === "function") {
    return documentObject.caretRangeFromPoint(clientX, clientY);
  }
  return null;
}

export function readerPositionFromPointer(root, event, chapterIndex) {
  if (!root || !event || event.button !== 0) return null;
  const documentObject = root.ownerDocument;
  const selection = documentObject.defaultView?.getSelection?.();
  const selectionRange = selection && !selection.isCollapsed && selection.rangeCount > 0
    ? selection.getRangeAt(0)
    : null;
  const range = readerBlockForNode(root, selectionRange?.startContainer)
    ? selectionRange
    : rangeAtPoint(documentObject, event.clientX, event.clientY);
  return readerPositionFromRange(root, range, chapterIndex);
}
