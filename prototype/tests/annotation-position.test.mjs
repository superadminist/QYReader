import test from "node:test";
import assert from "node:assert/strict";
import { annotationPopoverPosition, visibleAnnotationAnchor } from "../src/annotationPosition.js";

const bounds = { left: 100, right: 700, top: 80, bottom: 600 };
test("selection controls sit above the selected line without changing its coordinates", () => {
  const anchor = { left: 300, right: 400, top: 250, bottom: 275 };
  assert.deepEqual(annotationPopoverPosition(anchor, bounds, { width: 300, height: 44 }), { left: 200, top: 196, maxWidth: 584 });
  assert.equal(anchor.top, 250);
});
test("top-edge selection puts controls below and clamps the right edge", () => {
  const position = annotationPopoverPosition({ left: 640, right: 690, top: 85, bottom: 110 }, bounds, { width: 300, height: 44 });
  assert.equal(position.top, 120);
  assert.equal(position.left, 392);
});
test("expanded note editor and narrow reading area remain within their viewport", () => {
  const area = { left: 10, top: 10, right: 270, bottom: 300 };
  const position = annotationPopoverPosition({ left: 12, right: 28, top: 70, bottom: 90 }, area, { width: 360, height: 230 });
  assert.equal(position.left, 18);
  assert.equal(position.top, 62);
  assert.equal(position.maxWidth, 244);
});
test("scrolling an entire selection out of view dismisses its anchor", () => {
  assert.equal(visibleAnnotationAnchor([{ left: 150, right: 250, top: 40, bottom: 60, width: 100, height: 20 }], bounds), null);
});
test("multi-line selection anchors to a visible line and clips partial visibility", () => {
  const rects = [
    { left: 150, right: 250, top: 40, bottom: 60, width: 100, height: 20 },
    { left: 90, right: 250, top: 70, bottom: 95, width: 160, height: 25 },
  ];
  assert.deepEqual(visibleAnnotationAnchor(rects, bounds), { left: 100, right: 250, top: 80, bottom: 95 });
});
