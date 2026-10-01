// Real QWebEngine interaction gate; run via tests/ui_repair_qa.py.
import { spawnSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const env = process.env;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const output = env.DD_QA_SCREENSHOT_DIR;
const count = Number(env.DD_QA_CYCLES || 20);
const assert = (value, message) => { if (!value) throw new Error(message); };
const clients = [];
const evidence = { scaleFactor: Number(env.DD_QA_SCALE_FACTOR), systemScale: Number(env.DD_QA_SYSTEM_SCALE), qtMultiplier: Number(env.DD_QA_QT_MULTIPLIER), cycles: count, themes: [], frames: [], windowChecks: [], pointerResize: [], limitations: [] };
if (env.DD_QA_SINGLE_PROCESS === "1") evidence.limitations.push("QA-only single-process Chromium fallback; default production multiprocess compositor failed to start in this desktop environment.");

async function targets() { return (await fetch(`http://127.0.0.1:${env.DD_QA_CDP_PORT}/json/list`)).json(); }
async function poll(operation, message, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const result = await operation(); if (result) return result; await sleep(80); }
  throw new Error(message);
}
async function attach(floating = false) {
  const target = await poll(async () => (await targets()).find((item) => item.type === "page" && item.url.includes("/prototype/dist/client/index.html") && item.url.includes("surface=floating") === floating), "Qt target missing");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let id = 0;
  const pending = new Map();
  const client = { socket, events: [], call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const key = ++id;
      const timer = setTimeout(() => { pending.delete(key); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      pending.set(key, { resolve(value) { clearTimeout(timer); resolve(value); }, reject(error) { clearTimeout(timer); reject(error); } });
      socket.send(JSON.stringify({ id: key, method, params }));
    });
  } };
  socket.addEventListener("message", ({ data }) => {
    const payload = JSON.parse(data);
    if (!payload.id) return client.events.push(payload);
    const handler = pending.get(payload.id);
    if (!handler) return;
    pending.delete(payload.id);
    if (payload.error) handler.reject(new Error(payload.error.message)); else handler.resolve(payload.result);
  });
  await client.call("Runtime.enable");
  await client.call("Page.enable");
  clients.push(client);
  return client;
}
async function evaluate(client, expression) {
  const value = await client.call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (value.exceptionDetails) throw new Error(value.exceptionDetails.exception?.description || value.exceptionDetails.text);
  return value.result?.value;
}
async function native(client, method, argument) {
  const value = await evaluate(client, `new Promise(resolve => window.__qaNativeBridge[${JSON.stringify(method)}](${argument === undefined ? "" : `${JSON.stringify(argument)},`}resolve))`);
  const result = typeof value === "string" && value ? JSON.parse(value) : value;
  assert(result?.ok !== false, `${method}: ${JSON.stringify(result)}`);
  return result?.data;
}
function probe(action = "snapshot", args = []) {
  const result = spawnSync(env.DD_QA_PYTHON, [env.DD_QA_UI_PROBE, "--action", action, "--pid", env.DD_QA_HOST_PID, ...args], { encoding: "utf8", windowsHide: true });
  assert(result.status === 0, `Native probe failed: ${result.stderr}`);
  return JSON.parse(result.stdout);
}
function visual(role, cycle, flow = false) {
  const result = spawnSync(env.DD_QA_CAPTURE_PYTHON || env.DD_QA_PYTHON, [env.DD_QA_UI_PROBE, "--action", flow ? "flow" : "capture", "--pid", env.DD_QA_HOST_PID, "--role", role, "--cycle", String(cycle), "--output-dir", output, "--output", join(output, `${role}-${cycle}.png`)], { encoding: "utf8", windowsHide: true });
  assert(result.status === 0, `Desktop capture failed: ${result.stderr}`);
  const value = JSON.parse(result.stdout);
  evidence.frames.push(...(value.frames || [value]));
  return value;
}
async function screenshot(client, name) {
  try {
    const result = await client.call("Page.captureScreenshot", { format: "png" });
    await writeFile(join(output, name), Buffer.from(result.data, "base64"));
  } catch (error) { evidence.limitations.push(`${name}: ${error.message}`); }
}
async function viewport(client, role) {
  await sleep(120);
  const value = await evaluate(client, `(() => { const node = document.querySelector(${JSON.stringify(role === "main" ? ".mac-window" : ".native-floating-surface")}); const rect = node?.getBoundingClientRect(); return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,root:rect?{width:rect.width,height:rect.height}:null,mode:document.querySelector('.prototype-stage')?.dataset.windowMode,radius:node?getComputedStyle(node).borderRadius:null}; })()`);
  const win = probe().windows.find((item) => item.role === role);
  assert(win, `Missing ${role} native window`);
  assert(value.root, `Missing ${role} root surface`);
  assert(value.radius === (role === "main" && value.mode !== "normal" ? "0px" : role === "main" ? "22px" : "30px"), `Unexpected ${role} radius: ${value.radius}`);
  assert(Math.abs(value.dpr - evidence.scaleFactor) < .03, `Actual DPR ${value.dpr} differs from requested ${evidence.scaleFactor}`);
  assert(Math.abs(value.width * value.dpr - win.rect.width) <= 8 && Math.abs(value.height * value.dpr - win.rect.height) <= 8, `Native/Web viewport mismatch: ${JSON.stringify({ value, win })}`);
  evidence.windowChecks.push({ role, ...value, native: win.rect });
  return value;
}

try {
  const main = await attach();
  await main.call("Page.addScriptToEvaluateOnNewDocument", { source: `window.__qaInteractions=[]; (() => { let current; Object.defineProperty(window,'QWebChannel',{configurable:true,get:()=>current,set:Original=>{current=function(transport,callback,converters){return new Original(transport,channel=>{window.__qaNativeBridge=channel.objects.ddBridge;channel.objects.ddBridge.windowInteractionChanged.connect((surface,active)=>window.__qaInteractions.push({surface,active,at:performance.now()}));callback(channel)},converters)}}}); })();` });
  await main.call("Page.reload", { ignoreCache: true });
  await poll(() => evaluate(main, "Boolean(window.__qaNativeBridge) && document.querySelectorAll('.book-card').length === 10"), "Fixture library missing");
  const initialLibrary = await native(main, "getLibraryState");
  const initialOrder = await evaluate(main, "[...document.querySelectorAll('.book-card')].map(node=>node.dataset.bookId)");
  assert(initialOrder.join() === initialLibrary.books.map(book=>book.id).join(), "Restored library order differs from persisted server order");
  const initialState = await native(main, "getInitialState");
  assert(await evaluate(main, `document.querySelector('.prototype-stage').dataset.theme === ${JSON.stringify(initialState.preferences.theme)}`), "Persisted theme was not restored on startup");
  evidence.startup = { order: initialOrder, sortMode: initialLibrary.sortMode, theme: initialState.preferences.theme };
  assert(!await evaluate(main, "Boolean(document.querySelector('vite-error-overlay'))"), "Framework error overlay");
  probe("place", ["--role", "main", "--x", "60", "--y", "60", "--width", "1180", "--height", "1000"]);
  await sleep(300);
  await evaluate(main, "[...document.querySelectorAll('.library-sort-control button')].find(node=>node.innerText==='自定义排序').click()");
  await poll(() => evaluate(main, "Boolean(document.querySelector('.book-grid.sortable'))"), "Manual sort not enabled");
  await sleep(250); // Allow card FLIP animations after the mode switch to settle.
  await evaluate(main, "(()=>{const page=document.querySelector('.library-page');page.scrollTop+=document.querySelector('.book-grid').getBoundingClientRect().top-page.getBoundingClientRect().top-30})()");
  await sleep(220);
  const before = (await native(main, "getLibraryState")).books.map((book) => book.id);
  const points = await evaluate(main, `(() => { const cards=[...document.querySelectorAll('.book-card')]; const first=cards[0].getBoundingClientRect(); const target=cards.find(node=>node.getBoundingClientRect().top>first.top+10); const next=target?.getBoundingClientRect(); return next?{from:{x:first.left+first.width/2,y:first.top+50},to:{x:next.left+next.width*.25,y:next.top+50},target:target.dataset.bookId}:null; })()`);
  assert(points, "Library has no second visible row for cross-row drag");
  evidence.dragPoints = points;
  evidence.libraryViewport = await evaluate(main, "({width:innerWidth,height:innerHeight,scrollTop:document.querySelector('.library-page').scrollTop})");
  assert(points.to.y < evidence.libraryViewport.height - 8, "Cross-row target is outside the visible viewport; enlarge the test window before pointer input");
  assert(points.from.y > 54, "Drag source is clipped above the native title bar");
  await screenshot(main, "library-before-drag.png");
  await main.call("Input.dispatchMouseEvent", { type: "mousePressed", ...points.from, button: "left", clickCount: 1 });
  for (let step = 1; step <= 12; step++) {
    await main.call("Input.dispatchMouseEvent", { type: "mouseMoved", x: points.from.x + (points.to.x - points.from.x) * step / 12, y: points.from.y + (points.to.y - points.from.y) * step / 12, button: "left", buttons: 1 });
    await sleep(35);
  }
  await main.call("Input.dispatchMouseEvent", { type: "mouseReleased", ...points.to, button: "left", clickCount: 1 });
  const sorted = await poll(async () => { const state = await native(main, "getLibraryState"); return state.books.map(book=>book.id).join() !== before.join() ? state : null; }, "Cross-row drag did not persist");
  evidence.sort = { before, after: sorted.books.map(book=>book.id), target: points.target };
  await screenshot(main, "library-manual-order.png");
  await evaluate(main, "document.querySelector('.book-more').click()");
  assert(await evaluate(main, "[...document.querySelectorAll('[role=menuitem]')].some(node=>node.innerText.includes('打开源文件位置')&&!node.disabled)"), "Source-location menu action missing");
  await screenshot(main, "library-context-menu.png");
  await main.call("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await main.call("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await evaluate(main, "document.querySelector('.book-open').click()");
  await poll(() => evaluate(main, "Boolean(document.querySelector('.native-reader .reading-copy'))"), "Reader not ready");
  for (const theme of ["白天", "护眼", "米黄", "夜间"]) {
    await native(main, "updateAppPreferences", JSON.stringify({ patch: { theme } }));
    await poll(() => evaluate(main, `document.querySelector('.prototype-stage').dataset.theme === ${JSON.stringify(theme)}`), "Theme did not update");
    const colors = await evaluate(main, `(() => { const selectors=['.player-bar','.toolbar-center','.reading-sheet h1','.reading-copy','.toc-list .selected']; return Object.fromEntries(selectors.map(selector=>{const node=document.querySelector(selector); const style=getComputedStyle(node);return [selector,{color:style.color,background:style.backgroundColor}]})); })()`);
    if (theme === "夜间") {
      for (const selector of [".player-bar", ".toolbar-center"]) {
        const values = colors[selector].background.match(/\d+/g)?.map(Number);
        assert(values && Math.max(...values.slice(0,3)) < 130, `${selector} remains light in night mode: ${colors[selector].background}`);
      }
      const heading = colors[".reading-sheet h1"].color.match(/\d+/g).map(Number);
      assert(Math.min(...heading.slice(0,3)) > 120, "Chapter heading too dark in night mode");
    }
    evidence.themes.push({ theme, colors });
    await screenshot(main, `reader-theme-${theme}.png`);
  }
  for (let cycle = 0; cycle < count; cycle++) {
    visual("main", cycle, true);
    await viewport(main, "main");
    await native(main, "toggleMaximizeWindow");
    await poll(() => evaluate(main, "document.querySelector('.prototype-stage').dataset.windowMode==='maximized'"), "Maximize state mismatch");
    await native(main, "toggleMaximizeWindow");
    await poll(() => evaluate(main, "document.querySelector('.prototype-stage').dataset.windowMode==='normal'"), "Restore state mismatch");
    await viewport(main, "main");
    await native(main, "minimizeWindow");
    assert(!probe().windows.find(item=>item.role==="main").visible, "Main did not hide to tray");
    await native(main, "returnToMainWindow");
    await sleep(120);
    assert(probe().windows.find(item=>item.role==="main").visible, "Tray restore did not show main");
    await native(main, "showFloatingReader");
    const floating = await attach(true);
    await poll(() => evaluate(floating, "Boolean(document.querySelector('.native-floating-surface'))"), "Floating root missing");
    if (cycle === 0) { await sleep(350); await screenshot(floating, "floating-initial.png"); }
    visual("floating", cycle, true);
    await viewport(floating, "floating");
    await floating.call("Input.dispatchMouseEvent", { type: "mouseMoved", x: 160, y: 120 });
    await sleep(220);
    const point = await evaluate(floating, "(()=>{const rect=document.querySelector('.floating-resize-control').getBoundingClientRect();return {x:(rect.left+rect.width/2)*devicePixelRatio,y:(rect.top+rect.height/2)*devicePixelRatio}})()");
    const delta = cycle % 2 ? -35 : 35;
    const snapshot = probe("drag", ["--role", "floating", "--from-x", String(Math.round(point.x)), "--from-y", String(Math.round(point.y)), "--dx", String(delta), "--dy", String(delta)]);
    evidence.pointerResize.push({ cycle, mode: snapshot.dragMode, scale: evidence.scaleFactor });
    await viewport(floating, "floating");
    await native(main, "returnToMainWindow");
    floating.socket.close();
    await sleep(120);
  }
  await viewport(main, "main");
  await screenshot(main, "reader-final.png");
  await evaluate(main, "document.querySelector('button[aria-label=\"返回内容库\"]').click()");
  await poll(() => evaluate(main, "document.querySelectorAll('.book-card').length===10"), "Reader return did not restore the library");
  const returned = await native(main, "getLibraryState");
  const returnedOrder = await evaluate(main, "[...document.querySelectorAll('.book-card')].map(node=>node.dataset.bookId)");
  assert(returnedOrder.join() === returned.books.map(book=>book.id).join(), "Returning from reader displayed stale library order");
  assert(returned.sortMode === "manual", "Reading changed manual sort mode");
  evidence.returnedLibrary = { order: returnedOrder, sortMode: returned.sortMode };
  if (env.DD_QA_REVEAL_LOG) {
    await evaluate(main, "document.querySelector('.book-more').click()");
    await evaluate(main, "[...document.querySelectorAll('[role=menuitem]')].find(node=>node.innerText.includes('打开源文件位置')).click()");
    const revealed = await poll(async () => { try { return JSON.parse(await readFile(env.DD_QA_REVEAL_LOG,'utf8')); } catch { return null; } }, "Source-location menu did not reach the native backend");
    assert(revealed.path.includes("中文 空格") && revealed.path.endsWith('.txt'), "Source-location backend did not receive the original Chinese/space filename");
    evidence.sourceReveal = { ...revealed, explorer: "mocked: no Explorer process launched" };
  }
  evidence.consoleErrors = clients.flatMap(client=>client.events.filter(event=>event.method==="Runtime.exceptionThrown" || event.method==="Runtime.consoleAPICalled" && event.params?.type==="error"));
  evidence.nativeInteractions = await evaluate(main, "window.__qaInteractions");
  if (evidence.pointerResize.every(item=>item.mode!=="mouse")) evidence.limitations.push("Native pointer unavailable: size changes exercised SetWindowPos fallback; mouse-following smoothness requires an interactive desktop.");
  assert(evidence.consoleErrors.length === 0, `Runtime errors: ${JSON.stringify(evidence.consoleErrors)}`);
  if (!evidence.frames.some(frame=>frame.available)) evidence.limitations.push("Desktop screen capture is unavailable; CDP images alone do not prove absence of half-screen compositor glitches.");
  evidence.passed = true;
} catch (error) {
  evidence.passed = false;
  evidence.failure = error.stack;
  throw error;
} finally {
  await writeFile(env.DD_QA_CHECKPOINT, JSON.stringify(evidence, null, 2));
  for (const client of clients) client.socket.close();
}
process.stdout.write(JSON.stringify(evidence, null, 2));
