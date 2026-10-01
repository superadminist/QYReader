// Move one item relative to a stable identifier; never submit a stale whole-list snapshot.
export function moveLibraryBook(books, bookId, beforeBookId = null) {
  if (bookId === beforeBookId) return books;
  const book = books.find((item) => item.id === bookId);
  if (!book || (beforeBookId !== null && !books.some((item) => item.id === beforeBookId))) return books;
  const remaining = books.filter((item) => item.id !== bookId);
  const index = beforeBookId === null ? remaining.length : remaining.findIndex((item) => item.id === beforeBookId);
  return [...remaining.slice(0, index), book, ...remaining.slice(index)];
}

export function libraryDropTarget(books, bookId, targetId, after) {
  const others = books.filter((book) => book.id !== bookId);
  const index = others.findIndex((book) => book.id === targetId);
  if (index === -1) return undefined;
  return after ? others[index + 1]?.id ?? null : targetId;
}
