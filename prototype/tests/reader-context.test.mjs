import test from "node:test";
import assert from "node:assert/strict";
import { copyReaderText, readerContextTarget } from "../src/readerContext.js";

function clipboardFixture(protocol, writeText, copySuccess = true) {
  const calls = [];
  const range = { startContainer: { isConnected: true }, cloneRange() { return this; } };
  const selection = { rangeCount: 1, getRangeAt: () => range, removeAllRanges: () => calls.push("clear"), addRange: r => calls.push(r) };
  const field = { setAttribute() {}, style: {}, select: () => calls.push("select"), remove: () => calls.push("remove") };
  const doc = {
    defaultView: { location: { protocol }, navigator: { clipboard: { writeText } }, getSelection: () => selection },
    activeElement: { focus: () => calls.push("focus") },
    createElement: () => field,
    body: { append: () => calls.push("append") },
    execCommand: command => { calls.push(command); return copySuccess; },
  };
  return { doc, calls, field, range };
}

test("Qt file pages copy synchronously instead of waiting for unsupported clipboard permissions", async () => {
  const fixture = clipboardFixture("file:", () => { throw new Error("Must not invoke the file-page async clipboard"); });
  await copyReaderText("甲😀乙", fixture.doc);
  assert.equal(fixture.field.value, "甲😀乙");
  assert.deepEqual(fixture.calls, ["append", "select", "copy", "remove", "focus", "clear", fixture.range]);
});

test("browser clipboard rejection falls back without losing the reading selection", async () => {
  const fixture = clipboardFixture("https:", async () => { throw new Error("Permission denied"); });
  await copyReaderText("选中文字", fixture.doc);
  assert.ok(fixture.calls.includes("copy"));
  assert.equal(fixture.calls.at(-1), fixture.range);
});

test("failed copying reports an error and restores focus and selection", async () => {
  const fixture = clipboardFixture("file:", undefined, false);
  await assert.rejects(copyReaderText("文字", fixture.doc), /复制失败/);
  assert.ok(fixture.calls.includes("remove"));
  assert.ok(fixture.calls.includes("focus"));
  assert.equal(fixture.calls.at(-1), fixture.range);
});

test("blank reading space never reuses an unrelated selected range", () => {
  const root = { contains: () => false };
  const target = { closest: () => null };
  assert.deepEqual(readerContextTarget(root, { target, clientX: 10, clientY: 10 }, 2, []), { kind: "blank" });
});
