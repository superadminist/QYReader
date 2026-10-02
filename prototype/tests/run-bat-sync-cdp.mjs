// Drive the real Qt source host. The Python launcher starts it through run.bat.
const port = Number(process.env.DD_QA_CDP_PORT);
const title = process.env.DD_QA_BOOK_TITLE;
if (!port || !title) throw new Error("Missing run.bat QA environment");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const quote = (value) => JSON.stringify(value);

async function targets() {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  return (await response.json()).filter((target) => target.type === "page"
    && target.url?.includes("/prototype/dist/client/index.html"));
}

async function waitTarget(count = 1, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const found = await targets();
      if (found.length >= count && found[count - 1].webSocketDebuggerUrl) return found[count - 1];
    } catch { /* Qt is still starting. */ }
    await sleep(100);
  }
  throw new Error(`Expected ${count} Qt page target(s)`);
}

class Client {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.pending = new Map();
    this.id = 0;
  }
  async connect() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (message) => {
      const payload = JSON.parse(message.data);
      const pending = this.pending.get(payload.id);
      if (!pending) return;
      this.pending.delete(payload.id);
      clearTimeout(pending.timer);
      if (payload.error) pending.reject(new Error(payload.error.message));
      else pending.resolve(payload.result || {});
    });
    await this.call("Runtime.enable");
    await this.call("Page.enable");
  }
  call(method, params = {}, timeout = 10000) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout: ${method}`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const response = await this.call("Runtime.evaluate", {
      expression, returnByValue: true, awaitPromise: true,
    });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description
      || response.exceptionDetails.text || "Qt evaluation failed");
    return response.result?.value;
  }
  close() { this.socket.close(); }
}

async function waitFor(client, expression, message, timeout = 10000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await client.eval(expression)) return;
    await sleep(50);
  }
  throw new Error(message);
}

async function clickLabel(client, label) {
  return client.eval(`(() => {
    const button = [...document.querySelectorAll("button")]
      .find((item) => item.getAttribute("aria-label") === ${quote(label)});
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
}

function captureExpression() {
  return `({
    events: window.__qaPlaybackEvents || [],
    mark: document.querySelector(".reading-copy mark")?.innerText || "",
    player: document.querySelector(".player-copy small")?.innerText || "",
    floating: document.querySelector(".floating-lyric-layer.active [data-sentence-role=current]")?.innerText || "",
    status: document.querySelector(".floating-status")?.innerText || "",
  })`;
}

const mainTarget = await waitTarget();
const main = new Client(mainTarget.webSocketDebuggerUrl);
await main.connect();
await main.call("Page.addScriptToEvaluateOnNewDocument", { source: `
  window.__qaPlaybackEvents = [];
  (() => {
    let current = window.QWebChannel;
    const wrap = (Original) => {
      if (!Original || Original.__qaWrapped) return Original;
      function Wrapped(transport, callback, converters) {
        return new Original(transport, (channel) => {
          if (!window.__qaConnected) {
            window.__qaConnected = true;
            channel.objects.ddBridge.readerPlaybackChanged.connect((raw) => {
              try { window.__qaPlaybackEvents.push(JSON.parse(raw)); } catch {}
            });
          }
          callback(channel);
        }, converters);
      }
      Wrapped.__qaWrapped = true;
      return Wrapped;
    };
    Object.defineProperty(window, "QWebChannel", {
      configurable: true, get() { return current; },
      set(value) { current = wrap(value); },
    });
    if (current) current = wrap(current);
  })();
` });
await main.call("Page.reload", { ignoreCache: true });
await waitFor(main, `Boolean(document.body?.innerText.includes(${quote(title)}))`, "QA book missing", 20000);
await main.eval(`(() => {
  const card = [...document.querySelectorAll(".book-card")]
    .find((item) => item.innerText.includes(${quote(title)}));
  if (!card) return false;
  card.querySelector('.book-open').click(); return true;
})()`);
await waitFor(main, "Boolean(document.querySelector('.native-reader'))", "Reader did not open");
if (!await clickLabel(main, "播放")) throw new Error("Main Play was unavailable");
try {
  await waitFor(main, "window.__qaPlaybackEvents.some((event) => event.reason === 'sentenceStart')", "SAPI did not report a word", 15000);
} catch (error) {
  throw new Error(`${error.message}: ${JSON.stringify(await main.eval(`({ events: window.__qaPlaybackEvents,
    page: document.body?.innerText.slice(0, 600), connected: window.__qaConnected })`))}`);
}
await waitFor(main, "Boolean(document.querySelector('.reading-copy mark'))", "Main lyric missing");
const initial = await main.eval(captureExpression());
if (!await clickLabel(main, "暂停")) throw new Error("Main Pause was unavailable");
await sleep(150);
const paused = await main.eval(captureExpression());
if (paused.player !== initial.player || paused.mark !== initial.mark) {
  throw new Error(`Main lyric changed on Pause: ${JSON.stringify({ initial, paused })}`);
}
if (!await clickLabel(main, "播放")) throw new Error("Main Resume was unavailable");
await sleep(150);
const resumed = await main.eval(captureExpression());
const doneBefore = resumed.events.filter((event) => event.reason === "sentenceDone").length;
await waitFor(main, `window.__qaPlaybackEvents.filter((event) => event.reason === 'sentenceDone').length > ${doneBefore}`,
  "No SAPI sentence completion after Resume", 25000);
const boundaryBefore = await main.eval(captureExpression());
if (!await clickLabel(main, "暂停")) throw new Error("Boundary Pause was unavailable");
await sleep(100);
const boundaryPaused = await main.eval(captureExpression());
if (boundaryPaused.player !== boundaryBefore.player || boundaryPaused.mark !== boundaryBefore.mark) {
  throw new Error(`Main lyric changed at sentence boundary Pause: ${JSON.stringify({ boundaryBefore, boundaryPaused })}`);
}
if (!await clickLabel(main, "播放")) throw new Error("Boundary Resume was unavailable");
await sleep(100);
if (!await clickLabel(main, "切换到悬浮朗读")) throw new Error("Floating toggle missing");
await waitTarget(2);
const floatingTarget = (await targets()).find((target) => target.id !== mainTarget.id);
if (!floatingTarget) throw new Error("Could not identify floating target");
const floating = new Client(floatingTarget.webSocketDebuggerUrl);
await floating.connect();
try {
  await waitFor(floating, "Boolean(document.querySelector('.native-floating-surface'))", "Floating UI missing", 15000);
} catch (error) {
  throw new Error(`${error.message}: ${JSON.stringify(await floating.eval("({ text: document.body?.innerText.slice(0, 500), url: location.href })"))}`);
}
const timeline = [];
for (let cycle = 0; cycle < 12; cycle += 1) {
  await waitFor(floating, "Boolean(document.querySelector('.floating-play:not(:disabled)'))", "Floating control stuck");
  const before = await floating.eval(captureExpression());
  const button = await floating.eval("document.querySelector('.floating-play')?.getAttribute('aria-label')");
  if (!await clickLabel(floating, button)) throw new Error(`Floating ${button} unavailable`);
  await sleep(150);
  const after = await floating.eval(captureExpression());
  const mainAfter = await main.eval(captureExpression());
  timeline.push({ button, before: before.floating, after: after.floating,
    main: mainAfter.player, latestReasons: mainAfter.events.slice(-3).map((event) => event.reason) });
  if (button === "暂停" && after.floating !== before.floating) {
    throw new Error(`Floating lyric jumped on Pause: ${JSON.stringify(timeline)}`);
  }
  if (!mainAfter.player.endsWith(after.floating)) {
    throw new Error(`Main and floating lyrics differ: ${JSON.stringify(timeline)}`);
  }
}
let thirdSentence = null;
if (process.env.DD_QA_WAIT_THIRD_SENTENCE === "1") {
  const button = await floating.eval("document.querySelector('.floating-play')?.getAttribute('aria-label')");
  if (button === "播放" && !await clickLabel(floating, "播放")) {
    throw new Error("Could not resume for third sentence");
  }
  await waitFor(main,
    "Boolean(document.querySelector('.reading-copy mark')?.innerText?.includes('如图51所示'))",
    "Third SAPI sentence did not start", 60000);
  thirdSentence = await main.eval(captureExpression());
  const floatingThird = await floating.eval(captureExpression());
  if (!thirdSentence.player.endsWith(floatingThird.floating)) {
    throw new Error("Main and floating lyric differ at third sentence");
  }
}
process.stdout.write(`${JSON.stringify({ initial: { player: initial.player, mark: initial.mark },
  paused: { player: paused.player, mark: paused.mark },
  resumed: { player: resumed.player, mark: resumed.mark },
  boundary: { before: boundaryBefore.player, paused: boundaryPaused.player },
  timeline, thirdSentence: thirdSentence && { player: thirdSentence.player, mark: thirdSentence.mark } }, null, 2)}\n`);
floating.close();
main.close();
