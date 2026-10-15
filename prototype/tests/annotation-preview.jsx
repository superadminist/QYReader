import React, { useCallback, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BookOpen, Moon, Sun } from "@phosphor-icons/react";
import { NativeReader } from "../src/App.jsx";
import "../src/styles.css";

// This page mounts the production reader. All fixture records stay in memory;
// it never connects to Qt, the user's library, audio, or persistent storage.
const CHAPTERS = [
  {
    title: "第一章　把想法留在书页边",
    paragraphs: [
      "清晨的书桌旁，一杯茶还冒着热气。我翻开昨日读过的那一页，想给喜欢的句子留下一条轻轻的线，下次回来时，便能重新找到此刻的心情。",
      "阅读有时像走进一座安静的花园。遇到一句有意思的话，不必急着把它背下来；停一停，写下自己的想法，再慢慢往前走，沿途的风景就会变得清楚。",
      "窗边的小猫抬起头，看着书页上的符号：甲😀乙，春天🌱与星光✨。文字之间的距离可以改变，记下的那句话却应该仍在原处。",
      "这一段的结尾连接下一段的开头，可以一起选择，也可以只留下其中几个字。一条线跨过了换行，思路仍然是连贯的。",
      "到了新的一段，我们继续谈论耐心。把事情拆成容易理解的小步骤，先完成一件，再开始下一件，心里便会多一点从容。",
      "午后的阳光移过桌角，屋里变得明亮起来。我把原来的黄色划线换成绿色，又添上一句备注：这里值得再读一次。颜色只是路标，想法才是留下来的东西。",
      "有些笔记写得很长，有些只有几个字。它们都应该能被轻松找到，也应该允许修改；等到不再需要时，清理掉那条线，正文仍然平静地留在那里。",
      "读到这一页的末尾，我合上书，准备明天继续。今天留下的几条笔记，像口袋里的小石子，轻轻提醒我：走过的路，都有值得记住的细节。",
    ],
  },
  {
    title: "第二章　重新出发的早晨",
    paragraphs: [
      "第二天早晨，我打开另一章。新的文字带来新的问题，昨天的笔记仍然属于昨天的书页，不应该跟随一个旧选区落到今天的段落上。",
      "风吹动窗帘，桌上的纸张轻轻响了一声。我选中这句话，准备从这里开始朗读；文字的位置应当与声音的起点一致。",
      "在不同章节之间来回翻阅，像沿着一条小路往返。每一个路标都有自己的位置，每一条备注都有对应的那句话。",
      "我们也可以跨段落选中一段更长的文字，或者只记下一个表情😀。无论字体大小怎样调整，书页中的意思都不应该改变。",
      "夜色渐深，我将阅读界面切换成深色。浅浅的划线仍然清楚，小小的工具条就在手边，读完这一段，今天的阅读便告一段落。",
    ],
  },
].map((chapter, index) => {
  let offset = 0;
  const blocks = chapter.paragraphs.map((text, blockIndex) => {
    const block = { id: `fixture-${index}-${blockIndex}`, text, startOffset: offset, endOffset: offset + Array.from(text).length, startsParagraph: true };
    offset = block.endOffset + 2;
    return block;
  });
  const content = chapter.paragraphs.join("\n\n");
  return { ...chapter, index, blocks, content, charCount: Array.from(content).length };
});
const SESSION_ID = "annotation-preview-session";
const BOOK_ID = "annotation-preview-book";
const TOTAL_CHARS = CHAPTERS.reduce((sum, chapter) => sum + chapter.charCount, 0);
const codePointSlice = (text, start, end) => Array.from(text).slice(start, end).join("");
const windowFor = (chapterIndex) => {
  const chapter = CHAPTERS[chapterIndex];
  return { sessionId: SESSION_ID, bookId: BOOK_ID, chapterIndex, chapterTitle: chapter.title, chapterLength: chapter.charCount, windowStartOffset: 0, windowEndOffset: chapter.charCount, hasBefore: false, hasAfter: false, blocks: chapter.blocks };
};
const positionFor = (chapterIndex, charOffset = 0) => {
  const offset = Math.min(CHAPTERS[chapterIndex].charCount, Math.max(0, charOffset));
  const previous = CHAPTERS.slice(0, chapterIndex).reduce((sum, chapter) => sum + chapter.charCount, 0);
  return { chapterIndex, charOffset: offset, progressPercent: (previous + offset) / TOTAL_CHARS * 100 };
};
const initialNote = () => {
  const text = "给喜欢的句子留下一条轻轻的线";
  const utf16Start = CHAPTERS[0].content.indexOf(text);
  const startOffset = Array.from(CHAPTERS[0].content.slice(0, utf16Start)).length;
  return { id: "fixture-existing-note", chapterIndex: 0, chapterTitle: CHAPTERS[0].title, startOffset, endOffset: startOffset + Array.from(text).length, text, note: "这是一条已有笔记，点击划线可以查看、改色和删除。", kind: "annotation", color: "yellow", createdAt: 1, updatedAt: 1, locationValid: true };
};
const pageFor = (items) => ({ items: [...items], total: items.length, nextCursor: "" });
const initialState = () => {
  const position = positionFor(0);
  return {
    phase: "ready", pendingCommand: "", windowLoading: false, error: "",
    bookmarks: { status: "ready", page: pageFor([initialNote()]), error: "" },
    search: { status: "idle", page: null, error: "" },
    data: {
      sessionId: SESSION_ID,
      book: { id: BOOK_ID, title: "书页边的想法", author: "交互测试正文", format: "TXT", totalChars: TOTAL_CHARS, chapters: CHAPTERS.map(({ index, title, charCount }) => ({ index, title, charCount })) },
      position, window: windowFor(0), bookmarkCount: 1,
      settings: { fontSize: 21, fontFamily: '"Songti SC", "STSong", serif', lineSpacing: 1.9, paragraphMode: 2, firstLineIndent: true, ttsRate: 180, volume: 80 },
      playback: { status: "idle", sentence: null, position, fallbackActive: false },
    },
  };
};

function AnnotationPreview() {
  const [state, setState] = useState(initialState);
  const [dark, setDark] = useState(false);
  const [failWrites, setFailWrites] = useState(false);
  const [slowWrites, setSlowWrites] = useState(false);
  const [selectedStart, setSelectedStart] = useState(null);
  const [metrics, setMetrics] = useState({ adds: 0, updates: 0, removes: 0, saves: 0, deletes: 0, loads: 0, reads: 0, startChanges: 0 });
  const [lastAction, setLastAction] = useState("就绪；点击已有黄色划线，或选中文字。");
  const notesRef = useRef([initialNote()]);
  const nextIdRef = useRef(1);
  const startRef = useRef(null);
  const optionsRef = useRef({ failWrites, slowWrites });
  optionsRef.current = { failWrites, slowWrites };
  const count = useCallback((field) => setMetrics((old) => ({ ...old, [field]: old[field] + 1 })), []);
  const publishNotes = useCallback(() => {
    const page = pageFor(notesRef.current);
    setState((old) => ({ ...old, bookmarks: { status: "ready", page, error: "" }, data: { ...old.data, bookmarkCount: page.total } }));
    return page;
  }, []);
  const beforeWrite = useCallback(async (label) => {
    const options = { ...optionsRef.current };
    if (options.slowWrites) await new Promise((resolve) => setTimeout(resolve, 900));
    if (options.failWrites) { setLastAction(`${label}失败（测试开关）`); throw new Error("模拟保存失败：请关闭顶部的失败开关后重试。"); }
  }, []);
  const loadNotes = useCallback(async () => { count("loads"); return publishNotes(); }, [count, publishNotes]);
  const addNote = useCallback(async (input) => {
    count("adds");
    await beforeWrite("保存");
    const chapter = CHAPTERS[input.chapterIndex];
    if (!chapter || input.startOffset < 0 || input.endOffset > chapter.charCount || input.startOffset >= input.endOffset) throw new Error("笔记位置超出测试章节范围。");
    const text = codePointSlice(chapter.content, input.startOffset, input.endOffset).trim();
    const note = { ...input, id: `fixture-note-${nextIdRef.current++}`, chapterTitle: chapter.title, text, kind: input.kind || "bookmark", color: input.color || "yellow", note: input.note || "", createdAt: Date.now() / 1000, updatedAt: Date.now() / 1000, locationValid: true };
    notesRef.current = [...notesRef.current, note];
    publishNotes(); count("saves"); setLastAction(`已保存：${text}`);
    return note;
  }, [beforeWrite, count, publishNotes]);
  const removeNote = useCallback(async (id) => {
    count("removes");
    await beforeWrite("删除");
    if (!notesRef.current.some((note) => note.id === id)) throw new Error("测试笔记已不存在。");
    notesRef.current = notesRef.current.filter((note) => note.id !== id);
    publishNotes(); count("deletes"); setLastAction("已删除所选笔记");
    return { bookmarkId: id, removed: true };
  }, [beforeWrite, count, publishNotes]);
  const features = useMemo(() => ({ invoke: async (input) => {
    if (input.action !== "updateNote") throw new Error("此夹具仅验证笔记交互，不导出文件。");
    count("updates"); await beforeWrite("编辑");
    const existing = notesRef.current.find((note) => note.id === input.bookmarkId);
    if (!existing) throw new Error("测试笔记已不存在。");
    const updated = { ...existing, ...input.patch, updatedAt: Date.now() / 1000 };
    notesRef.current = notesRef.current.map((note) => note.id === updated.id ? updated : note);
    count("saves"); setLastAction(`已更新：${updated.text}`);
    return { data: updated };
  } }), [beforeWrite, count]);
  const chooseStart = useCallback((target) => { startRef.current = target; setSelectedStart(target); count("startChanges"); }, [count]);
  const navigate = useCallback(async (target) => {
    let chapterIndex = target.chapterIndex ?? 0;
    let charOffset = target.charOffset ?? 0;
    if (target.kind === "percent") {
      charOffset = Math.round(TOTAL_CHARS * target.percent / 100);
      while (chapterIndex < CHAPTERS.length - 1 && charOffset >= CHAPTERS[chapterIndex].charCount) charOffset -= CHAPTERS[chapterIndex++].charCount;
    }
    const position = positionFor(chapterIndex, charOffset);
    startRef.current = null; setSelectedStart(null);
    setState((old) => ({ ...old, data: { ...old.data, position, window: windowFor(chapterIndex), playback: { ...old.data.playback, position, sentence: null } } }));
    return true;
  }, []);
  const command = useCallback(async (action) => {
    const target = startRef.current;
    if (action === "play") {
      count("reads"); setLastAction(target ? `朗读起点：第 ${target.chapterIndex + 1} 章，字符 ${target.charOffset}` : "从当前阅读位置朗读（无音频）");
      startRef.current = null; setSelectedStart(null);
    }
    setState((old) => {
      const position = target && action === "play" ? positionFor(target.chapterIndex, target.charOffset) : old.data.position;
      const text = codePointSlice(CHAPTERS[position.chapterIndex].content, position.charOffset, position.charOffset + 24);
      const sentence = action === "play" ? { chapterIndex: position.chapterIndex, startOffset: position.charOffset, endOffset: position.charOffset + Array.from(text).length, text } : action === "stop" ? null : old.data.playback.sentence;
      return { ...old, data: { ...old.data, position, playback: { ...old.data.playback, position, sentence, status: action === "pause" ? "paused" : action === "stop" ? "idle" : "playing" } } };
    });
  }, [count]);
  const search = (query) => {
    const results = CHAPTERS.flatMap((chapter) => {
      const index = chapter.content.indexOf(query);
      if (index < 0) return [];
      const startOffset = Array.from(chapter.content.slice(0, index)).length;
      return [{ id: `search-${chapter.index}`, chapterIndex: chapter.index, chapterTitle: chapter.title, startOffset, excerpt: codePointSlice(chapter.content, Math.max(0, startOffset - 12), startOffset + 48) }];
    });
    setState((old) => ({ ...old, search: { status: "ready", error: "", page: { total: results.length, results } } }));
  };
  return <div className={`prototype-stage theme-${dark ? "dark" : "light"}`} data-theme="白天">
    <div className="mac-window" style={{ display: "grid", gridTemplateRows: "54px minmax(0, 1fr) 56px" }}>
      <header className="mac-titlebar" style={{ justifyContent: "space-between", padding: "0 16px", gap: 14 }}>
        <strong className="app-title">划线笔记交互验证</strong>
        <div style={{ display: "flex", alignItems: "center", gap: 14, color: "var(--ui-text)", fontSize: 12 }}>
          <label><input type="checkbox" checked={failWrites} onChange={(event) => setFailWrites(event.target.checked)} />模拟保存失败</label>
          <label><input type="checkbox" checked={slowWrites} onChange={(event) => setSlowWrites(event.target.checked)} />慢响应（900ms）</label>
          <button className="icon-button" aria-label={dark ? "切换浅色主题" : "切换深色主题"} onClick={() => setDark((value) => !value)}>{dark ? <Sun /> : <Moon />}</button>
        </div>
      </header>
      <div className="app-body" style={{ height: "100%", minHeight: 0 }}>
        <aside className="rail"><div className="brand-mark"><BookOpen /></div><small style={{ color: "var(--ui-muted)", marginTop: 20, writingMode: "vertical-rl" }}>仅内存测试</small></aside>
        <main className="content-area">
          <NativeReader
            state={state} networkNotice={null} selectedStart={selectedStart}
            onChooseStart={chooseStart} onNavigate={navigate}
            onBack={() => setLastAction("此夹具直接展示生产阅读器")}
            onGetWindow={(chapterIndex) => navigate({ kind: "position", chapterIndex, charOffset: 0 })}
            onUpdatePosition={(chapterIndex, charOffset) => setState((old) => ({ ...old, data: { ...old.data, position: positionFor(chapterIndex, charOffset) } }))}
            onSearch={search} onLoadBookmarks={loadNotes} onAddBookmark={addNote}
            onRemoveBookmark={removeNote} onBookmarkSaved={publishNotes} onCommand={command}
            onSettings={(patch) => setState((old) => ({ ...old, data: { ...old.data, settings: { ...old.data.settings, ...patch } } }))}
            floatingAvailable={false} floatingVisible={false} onFloatingToggle={() => {}}
            onOpenSettings={() => setDark((value) => !value)} features={features}
          />
        </main>
      </div>
      <footer aria-label="交互验证状态" style={{ background: "var(--ui-panel)", color: "var(--ui-muted)", borderTop: "1px solid var(--ui-border)", padding: "7px 16px", fontSize: 11, lineHeight: 1.7, overflow: "hidden" }}>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <output data-testid="note-count">笔记 {state.bookmarks.page.items.length}</output>
          <output data-testid="save-count">保存成功 {metrics.saves}</output>
          <output data-testid="delete-count">删除成功 {metrics.deletes}</output>
          <output data-testid="write-calls">请求：新增 {metrics.adds} / 编辑 {metrics.updates} / 删除 {metrics.removes}</output>
          <output data-testid="read-count">朗读 {metrics.reads}</output>
          <output data-testid="start-count">选起点 {metrics.startChanges}</output>
          <output data-testid="selected-start">起点 {selectedStart ? `${selectedStart.chapterIndex + 1}:${selectedStart.charOffset}` : "未选择"}</output>
          <output data-testid="load-count">加载 {metrics.loads}</output>
        </div>
        <output data-testid="last-action" style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lastAction}</output>
      </footer>
    </div>
  </div>;
}

createRoot(document.getElementById("root")).render(<AnnotationPreview />);
