import { memo } from "react";
import { DotsThreeVertical, Play } from "@phosphor-icons/react";
import { STATUS_NAMES } from "./ReaderFeatures.jsx";

// A viewport change must not re-render cards that stay in the mounted window.
const LibraryBookCard = memo(function LibraryBookCard({ book, selectionMode, selected, dragging, justImported, readerEnabled, actions }) {
  return (
    <div data-book-id={book.id} className={`book-card ${selected ? "batch-selected" : ""} ${dragging ? "dragging" : ""} ${justImported ? "just-imported" : ""}`} onContextMenu={(event) => actions.showMenu(event, book)} onPointerDown={(event) => { if (!selectionMode) actions.startDrag(event, book); }} onPointerMove={actions.moveDrag} onPointerUp={actions.finishDrag} onPointerCancel={actions.cancelDrag}>
      <button className="book-open" aria-label={`${selectionMode ? "选择" : "阅读"} ${book.title}`} aria-disabled={!selectionMode && !readerEnabled} onClick={() => actions.open(book)}>
        <div className="cover-wrap"><img src={book.coverUrl} alt="" draggable={false} /><span className="format-badge">{book.format || "TXT"}</span><span className="resume-pill"><Play weight="fill" /> 继续</span></div>
        <strong>{book.title}</strong><small>{book.currentChapterTitle || book.author || "尚未开始阅读"}</small><div className="book-progress"><span style={{ width: `${book.progressPercent}%` }} /></div><em>{STATUS_NAMES[book.readingStatus] || (book.progressPercent >= 100 ? "已读" : book.progressPercent > 0 ? "阅读中" : "未读")} · {book.progressPercent}%</em>
      </button>
      {selectionMode ? <label className="book-selection" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`选择书籍 ${book.title}`} checked={selected} onChange={() => actions.toggleSelection(book.id)} /></label> : null}
      <button className="book-more" aria-label={`${book.title}的更多操作`} title="更多操作" onClick={(event) => actions.showMenu(event, book)}><DotsThreeVertical weight="bold" /></button>
    </div>
  );
});

export default LibraryBookCard;
