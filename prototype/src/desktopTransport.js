// Adapt isolated desktop hosts to the existing schemaVersion 2 connection.
// No React components or visual styles depend on the choice of shell.
const SIGNALS = [
  "windowStateChanged", "windowInteractionChanged", "bridgeError", "importProgress",
  "importFinished", "readerOpened", "readerSearchFinished", "readerPlaybackChanged",
  "floatingReaderChanged", "floatingPointerChanged", "appPreferencesChanged",
  "speechPreferencesChanged", "softwareUpdateChanged", "featuresChanged",
];
let handshakeSequence = 0;

export async function desktopNativeProxy(host) {
  if (host?.protocolVersion !== 1 || typeof host.invoke !== "function" || typeof host.subscribe !== "function") {
    throw new Error("桌面连接不可用或协议不兼容。");
  }
  const handshakeId = `handshake:${++handshakeSequence}`;
  const hello = await host.invoke("lab.handshake", [], { requestId: handshakeId });
  if (hello.protocolVersion !== 1 || hello.schemaVersion !== 2 || !hello.runId || !Array.isArray(hello.methods)) {
    throw new Error("桌面服务握手失败。");
  }
  await host.consumed?.(handshakeId);
  const listeners = new Map(SIGNALS.map((name) => [name, new Set()]));
  const active = new Set();
  let sequence = 0;
  let disposed = false;
  const unsubscribe = host.subscribe((event) => {
    if (event.runId !== hello.runId || event.type !== "event") return;
    for (const callback of listeners.get(event.name) || []) callback(...event.args);
  });
  const proxy = { disposeTransport() {
    disposed = true;
    unsubscribe();
    for (const requestId of active) Promise.resolve(host.cancel?.(requestId)).catch(() => {});
    active.clear();
  } };
  for (const [name, callbacks] of listeners) {
    proxy[name] = { connect: (cb) => callbacks.add(cb), disconnect: (cb) => callbacks.delete(cb) };
  }
  for (const method of hello.methods) {
    proxy[method] = (...args) => {
      const callback = typeof args.at(-1) === "function" ? args.pop() : null;
      if (disposed) return Promise.reject(new Error("DESKTOP_CONNECTION_DISPOSED"));
      const requestId = typeof host.consumed === "function"
        ? `${hello.runId}:${handshakeId}:${++sequence}`
        : `${hello.runId}:${++sequence}`;
      active.add(requestId);
      const pending = host.invoke(method, args, { requestId });
      const consumed = pending.then(async (result) => {
        try {
          if (callback) await callback(result);
          await host.consumed?.(requestId);
          return result;
        } catch (error) {
          host.consumerFailed?.(requestId, error);
          throw error;
        }
      }, async (error) => {
        // Rejected service results also have a terminal page receipt.
        await host.consumed?.(requestId);
        throw error;
      }).finally(() => active.delete(requestId));
      // Callback consumers also receive rejection through invokeWithResult.
      if (callback) return consumed;
      consumed.catch((error) => {
        for (const cb of listeners.get("bridgeError")) cb(error.message);
      });
      return consumed;
    };
  }
  return proxy;
}
