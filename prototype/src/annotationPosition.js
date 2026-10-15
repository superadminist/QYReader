// Keep the floating controls inside the visible reading area without moving text.
export function annotationPopoverPosition(anchor, bounds, size, gap = 10) {
  const inset = 8;
  const width = Math.min(size.width, Math.max(0, bounds.right - bounds.left - inset * 2));
  const left = Math.max(bounds.left + inset, Math.min((anchor.left + anchor.right - width) / 2, bounds.right - width - inset));
  const above = anchor.top - size.height - gap;
  const below = anchor.bottom + gap;
  const top = above >= bounds.top + inset ? above : below;
  return { left, top: Math.max(bounds.top + inset, Math.min(top, bounds.bottom - size.height - inset)), maxWidth: bounds.right - bounds.left - inset * 2 };
}

export function visibleAnnotationAnchor(rects, bounds) {
  const visible = Array.from(rects).filter((rect) => rect.width > 0 && rect.height > 0 && rect.bottom > bounds.top && rect.top < bounds.bottom && rect.right > bounds.left && rect.left < bounds.right);
  if (!visible.length) return null;
  const rect = visible[0];
  return { left: Math.max(rect.left, bounds.left), right: Math.min(rect.right, bounds.right), top: Math.max(rect.top, bounds.top), bottom: Math.min(rect.bottom, bounds.bottom) };
}
