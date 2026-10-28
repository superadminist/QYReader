const ROW_BATCH = 8;

// The grid offset is measured in scroll-content coordinates, so scrolling only
// needs scrollTop; it never needs to measure a card or flush layout.
export function libraryViewportTop(scrollTop, gridOffset, rowHeight) {
  return Math.floor(Math.max(0, scrollTop - gridOffset) / rowHeight / ROW_BATCH) * rowHeight * ROW_BATCH;
}

export function libraryWindow(bookCount, { columns, rowHeight, top, height }, virtual) {
  const totalRows = Math.ceil(bookCount / columns);
  if (!virtual || totalRows === 0) return { totalRows, firstRow: 0, endRow: totalRows };

  // A filter or a responsive column change can shorten the grid before the
  // browser clamps scrollTop. Keep a full final window mounted in that frame.
  const viewportTop = Math.min(Math.max(0, top), Math.max(0, totalRows * rowHeight - height));
  const firstRow = Math.max(0, Math.floor(viewportTop / rowHeight / ROW_BATCH) * ROW_BATCH - ROW_BATCH);
  const endRow = Math.min(totalRows, Math.ceil((viewportTop + height) / rowHeight / ROW_BATCH) * ROW_BATCH + ROW_BATCH);
  return { totalRows, firstRow, endRow };
}
