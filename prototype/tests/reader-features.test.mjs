import test from "node:test";
import assert from "node:assert/strict";
import { readerSelectionFromRange } from "../src/readerPosition.js";
import { connectBridge } from "../src/bridge.js";

test("selection endpoints across blocks use code points rather than UTF16 offsets", () => {
  const first = { dataset: { startOffset: "0" }, textContent: "甲😀乙" };
  const second = { dataset: { startOffset: "3" }, textContent: "第二段" };
  const node = (block) => ({ nodeType: 3, textContent: block.textContent, parentElement: { closest: () => block } });
  const a = node(first), b = node(second);
  const root = { contains: () => true, ownerDocument: { createRange: () => {
    let text = "";
    return { selectNodeContents: () => {}, setEnd(n, offset) { text = n.textContent.slice(0, offset); }, toString: () => text };
  } } };
  const range = { collapsed: false, startContainer: a, startOffset: 1, endContainer: b, endOffset: 2, toString: () => "😀乙第二", cloneRange: () => ({ startContainer: b, startOffset: 2, collapse: () => {} }) };
  assert.deepEqual(readerSelectionFromRange(root, range, 4), { chapterIndex: 4, startOffset: 1, endOffset: 5, text: "😀乙第二" });
});

test("demo classification edits retain reading progress and delete only references", async () => {
  const c = await connectBridge();
  const book = c.initialState.data.library.books[0];
  const progress = book.progressPercent;
  const terms = await c.features.invoke({ action: "organizationUpdate", request: { action: "create", kind: "categories", name: "学习" } });
  const id = terms.data.categories[0].id;
  await c.features.invoke({ action: "organizationUpdate", request: { action: "book", bookId: book.id, patch: { categoryId: id, tagIds: ["to-read"], readingStatus: "read", statusMode: "manual" } } });
  let state = (await c.library.getState()).data;
  assert.equal(state.books.find(x=>x.id===book.id).progressPercent, progress);
  assert.equal(state.books.find(x=>x.id===book.id).readingStatus, "read");
  await c.features.invoke({ action: "organizationUpdate", request: { action: "delete", kind: "categories", id } });
  state = (await c.library.getState()).data;
  assert.equal(state.books.find(x=>x.id===book.id).categoryId, "");
  assert.deepEqual(state.books.find(x=>x.id===book.id).tagIds, ["to-read"]);
  c.dispose();
});

test("browser model management explains its desktop boundary and stats have no invented history", async () => {
  const c = await connectBridge();
  assert.equal((await c.features.invoke({ action: "modelState" })).data.status, "missing");
  await assert.rejects(c.features.invoke({ action: "modelDownload" }), error=>error.code==="FEATURE_DESKTOP_REQUIRED");
  const stats = (await c.features.invoke({ action: "statistics" })).data;
  assert.equal(stats.total.totalMs, 0);
  assert.deepEqual(stats.days, []);
  c.dispose();
});

test("demo model variant is explicit and changes package metadata without downloading", async () => {
  const c = await connectBridge();
  try {
    let state = (await c.features.invoke({ action: "modelState" })).data;
    assert.equal(state.variant, "int8");
    assert.equal(state.modelId, "kokoro-v1.0-int8");
    assert.equal(state.totalBytes, 132303094);
    state = (await c.features.invoke({ action: "modelVariant", variant: "fp32" })).data;
    assert.equal(state.variant, "fp32");
    assert.equal(state.modelId, "kokoro-v1.0-fp32");
    assert.equal(state.totalBytes, 349906910);
    assert.equal(state.status, "missing");
    assert.equal(state.downloadedBytes, 0);
    assert.equal(state.installedBytes, 0);
    assert.equal((await c.features.invoke({ action: "modelState" })).data.variant, "fp32");
    await assert.rejects(c.features.invoke({ action: "modelDownload" }), error => error.code === "FEATURE_DESKTOP_REQUIRED");
    await assert.rejects(c.features.invoke({ action: "modelVariant", variant: "other" }), error => error.code === "MODEL_VARIANT_INVALID");
    assert.equal((await c.features.invoke({ action: "modelState" })).data.variant, "fp32");
    state = (await c.features.invoke({ action: "modelVariant", variant: "int8" })).data;
    assert.equal(state.modelId, "kokoro-v1.0-int8");
    assert.equal(state.totalBytes, 132303094);
  } finally { c.dispose(); }
});

test("demo model variant waits for a stopped playback session", async () => {
  const c = await connectBridge();
  try {
    const sessionId = (await c.floating.show()).data.sessionId;
    for (const command of ["play", "pause"]) {
      await c.reader.controlPlayback({ sessionId, command });
      await assert.rejects(c.features.invoke({ action: "modelVariant", variant: "fp32" }), error => error.code === "MODEL_BUSY");
      assert.equal((await c.features.invoke({ action: "modelState" })).data.variant, "int8");
    }
    await c.reader.controlPlayback({ sessionId, command: "stop" });
    assert.equal((await c.features.invoke({ action: "modelVariant", variant: "fp32" })).data.variant, "fp32");
  } finally { c.dispose(); }
});
