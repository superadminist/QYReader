import test from "node:test";
import assert from "node:assert/strict";
import { libraryViewportTop, libraryWindow } from "../src/libraryViewport.js";

const viewport = { columns: 4, rowHeight: 400, top: 0, height: 800 };

test("scroll positions use the cached grid offset and advance only at eight-row boundaries", () => {
  assert.equal(libraryViewportTop(0, 360, 400), 0);
  assert.equal(libraryViewportTop(360, 360, 400), 0);
  assert.equal(libraryViewportTop(3559, 360, 400), 0);
  assert.equal(libraryViewportTop(3560, 360, 400), 3200);
  assert.equal(libraryViewportTop(6759, 360, 400), 3200);
  assert.equal(libraryViewportTop(6760, 360, 400), 6400);
});

test("virtual windows retain overscan and never extend beyond the first or last book", () => {
  assert.deepEqual(libraryWindow(1025, viewport, true), { totalRows: 257, firstRow: 0, endRow: 16 });
  assert.deepEqual(libraryWindow(1025, { ...viewport, top: 6400 }, true), { totalRows: 257, firstRow: 8, endRow: 32 });
  const end = libraryWindow(1025, { ...viewport, top: 200000 }, true);
  assert.equal(end.endRow, 257);
  assert.ok(end.firstRow < 255, "a full final viewport and overscan remain mounted");
});

test("filtering a scrolled library to a shorter or empty list leaves a valid final window", () => {
  assert.deepEqual(libraryWindow(12, { ...viewport, top: 64000 }, true), { totalRows: 3, firstRow: 0, endRow: 3 });
  assert.deepEqual(libraryWindow(0, { ...viewport, top: 64000 }, true), { totalRows: 0, firstRow: 0, endRow: 0 });
  const shortened = libraryWindow(100, { ...viewport, top: 64000 }, true);
  assert.deepEqual(shortened, { totalRows: 25, firstRow: 8, endRow: 25 });
});

test("responsive columns and row sizes keep every visible row inside the mounted window", () => {
  for (const columns of [2, 3, 4, 6]) {
    for (const rowHeight of [280, 400, 530]) {
      const top = libraryViewportTop(6760, 360, rowHeight);
      const bounds = libraryWindow(1025, { ...viewport, columns, rowHeight, top }, true);
      const visibleFirstRow = Math.floor((6760 - 360) / rowHeight);
      const visibleEndRow = Math.ceil((6760 - 360 + viewport.height) / rowHeight);
      assert.ok(bounds.firstRow <= visibleFirstRow, `${columns} columns / ${rowHeight}px first row`);
      assert.ok(bounds.endRow >= visibleEndRow, `${columns} columns / ${rowHeight}px final row`);
      assert.equal(bounds.totalRows, Math.ceil(1025 / columns));
    }
  }
});

test("manual and small libraries keep every book mounted", () => {
  assert.deepEqual(libraryWindow(1025, { ...viewport, top: 64000 }, false), { totalRows: 257, firstRow: 0, endRow: 257 });
});
