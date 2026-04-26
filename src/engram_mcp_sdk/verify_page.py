"""Static HTML for the localhost verification page.

Kept in its own module so it can be unit-tested without spinning up a server,
and so the JS lives in one easily-auditable place.

The page implements World ID's recommended IDKit UX (see [the design
guidelines][dg]) without pulling in React or the deprecated
`@worldcoin/idkit-standalone` package:

1. Fetches IDKit init config (``app_id``, ``action``, ``rp_context``) from
   the local server, which proxies to engram-server.
2. Calls ``IDKit.request(...)`` from `@worldcoin/idkit-core` (loaded from
   esm.sh) to get a ``connectorURI`` -- a universal link that doubles as
   the QR-code payload (desktop) and a deep link into World App (mobile).
3. Renders the connector URI as a **QR code** (rendered with `qrcode`
   from esm.sh -- the same library used by ``@worldcoin/idkit``) and a
   prominent **"Open in World App"** button. Mobile user-agents see the
   deep-link button promoted above the QR code so a single tap launches
   World App without any scanning.
4. Polls for completion and walks through the status states recommended by
   IDKit's design guidelines (idle / scanning / exchanging / success /
   canceled / connection-lost / error). On error or cancel, a
   "Try again" affordance re-runs the flow without a page reload.
5. On success, POSTs the proof to ``/proof`` (which forwards it to
   engram-server and persists the resulting access token).
6. If the user clicks "I'd rather not", POSTs to ``/decline`` instead so
   the SDK remembers their preference.

The page is intentionally dependency-free at server start time -- everything
loads from CDNs at runtime so the SDK doesn't have to bundle JS, and the
host process never has to install Node.

[dg]: https://docs.world.org/world-id/idkit/design-guidelines
"""

VERIFY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Engram - Connect your World ID</title>
<style>
  :root {
    --bg: #0e0e10;
    --card: #16161a;
    --card-border: #26262c;
    --muted: #b3b3b8;
    --subtle: #8a8a92;
    --accent: #4f46e5;
    --accent-hover: #5e55ee;
    --decline: #2a2a2e;
    --decline-hover: #34343a;
    --ok: #16a34a;
    --warn: #f59e0b;
    --err: #ef4444;
    --link: #93c5fd;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      sans-serif;
    margin: 0;
    background: radial-gradient(
      1200px 600px at 50% -200px, #1c1c25 0%, var(--bg) 60%
    );
    color: #eaeaea;
    display: flex;
    min-height: 100vh;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .card {
    width: 460px;
    max-width: 100%;
    background: var(--card);
    border: 1px solid var(--card-border);
    border-radius: 16px;
    padding: 28px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 18px;
    color: var(--muted);
    font-size: 13px;
    letter-spacing: 0.02em;
  }
  .brand-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: linear-gradient(135deg, #ffffff 0%, #6b7280 100%);
    box-shadow: 0 0 0 3px rgba(255,255,255,0.06);
  }
  .brand strong { color: #ffffff; font-weight: 600; }
  h1 {
    font-size: 22px;
    margin: 0 0 8px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  p.lead {
    margin: 0 0 20px;
    color: var(--muted);
    line-height: 1.55;
    font-size: 14px;
  }
  .qr-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    padding: 22px;
    background: #ffffff;
    border-radius: 12px;
    margin-bottom: 16px;
  }
  .qr-wrap.dark {
    background: #0a0a0c;
    border: 1px solid var(--card-border);
  }
  .qr-wrap svg, .qr-wrap canvas {
    width: 200px;
    height: 200px;
    display: block;
  }
  .qr-caption {
    color: #1f2937;
    font-size: 13px;
    text-align: center;
  }
  .qr-wrap.dark .qr-caption { color: var(--muted); }
  .qr-skeleton {
    width: 200px;
    height: 200px;
    border-radius: 8px;
    background: linear-gradient(
      90deg,
      #ececec 0%, #f7f7f7 50%, #ececec 100%
    );
    background-size: 200% 100%;
    animation: shimmer 1.4s linear infinite;
  }
  .qr-wrap.dark .qr-skeleton {
    background: linear-gradient(
      90deg, #15151a 0%, #1d1d24 50%, #15151a 100%
    );
    background-size: 200% 100%;
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .deeplink {
    display: block;
    text-align: center;
    text-decoration: none;
    background: var(--accent);
    color: white;
    font-weight: 600;
    font-size: 14px;
    padding: 12px 14px;
    border-radius: 10px;
    margin-bottom: 12px;
  }
  .deeplink:hover { background: var(--accent-hover); }
  .deeplink[aria-disabled="true"] { opacity: 0.5; pointer-events: none; }
  .row { display: flex; gap: 10px; margin-top: 4px; }
  button {
    flex: 1;
    padding: 12px 14px;
    border-radius: 10px;
    border: 0;
    font-weight: 600;
    cursor: pointer;
    font-size: 14px;
    font-family: inherit;
  }
  .verify { background: var(--accent); color: white; }
  .verify:hover { background: var(--accent-hover); }
  .decline { background: var(--decline); color: #d6d6d6; }
  .decline:hover { background: var(--decline-hover); }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  .status {
    margin-top: 18px;
    padding: 12px 14px;
    border-radius: 10px;
    background: #0b0b0d;
    border: 1px solid var(--card-border);
    font-size: 13px;
    color: var(--muted);
    line-height: 1.5;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    min-height: 1.4em;
  }
  .status.hidden { display: none; }
  .status .dot {
    flex-shrink: 0;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--subtle);
    margin-top: 6px;
  }
  .status.scanning .dot { background: var(--accent); animation: pulse 1.2s ease-in-out infinite; }
  .status.exchanging .dot { background: var(--warn); animation: pulse 1.2s ease-in-out infinite; }
  .status.ok .dot { background: var(--ok); }
  .status.err .dot { background: var(--err); }
  @keyframes pulse {
    0% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(1.4); }
    100% { opacity: 1; transform: scale(1); }
  }
  .status .body { flex: 1; }
  .footer {
    margin-top: 18px;
    text-align: center;
    color: var(--subtle);
    font-size: 12px;
  }
  .footer a { color: var(--link); text-decoration: none; }
  .footer a:hover { text-decoration: underline; }
  .hide-on-mobile { display: block; }
  .show-on-mobile { display: none; }
  .desktop-instr { color: var(--subtle); font-size: 12px; margin-top: 8px; text-align: center; }
  @media (max-width: 480px) {
    .hide-on-mobile { display: none; }
    .show-on-mobile { display: block; }
  }
</style>
</head>
<body>
<div class="card" role="main" aria-labelledby="title">
  <div class="brand">
    <span class="brand-dot" aria-hidden="true"></span>
    <span>Engram &times; <strong>World ID</strong></span>
  </div>
  <h1 id="title">Connect your World ID</h1>
  <p class="lead">
    Engram's memory tools (<code>learn</code> and <code>recall</code>) are
    gated on a one-time proof of personhood. Verify with World App and
    you'll never have to do this again on this machine.
  </p>

  <!-- Mobile: deep-link first, QR hidden behind a toggle. -->
  <a id="deeplink" class="deeplink show-on-mobile" href="#"
     aria-disabled="true">Open in World App</a>

  <!-- Desktop: QR primary, deep-link as a fallback button below. -->
  <div id="qr-wrap" class="qr-wrap hide-on-mobile">
    <div id="qr" class="qr-skeleton" aria-label="QR code for World App"></div>
    <div class="qr-caption">
      Scan with <strong>World App</strong> on your phone
    </div>
  </div>
  <a id="deeplink-desktop" class="deeplink hide-on-mobile" href="#"
     aria-disabled="true"
     style="background: var(--decline); color: #e6e6e6;">
    Or open in World App on this device
  </a>

  <div class="row">
    <button class="verify" id="verify">Verify with World ID</button>
    <button class="decline" id="decline">I'd rather not</button>
  </div>

  <div id="status" class="status hidden" role="status" aria-live="polite">
    <span class="dot" aria-hidden="true"></span>
    <span class="body" id="status-body"></span>
  </div>

  <div class="footer">
    <a href="https://world.org/legal/terms" target="_blank" rel="noopener">
      Terms
    </a>
    &nbsp;&middot;&nbsp;
    <a href="https://world.org/legal/privacy" target="_blank" rel="noopener">
      Privacy
    </a>
  </div>
</div>

<script type="module">
  const statusEl = document.getElementById("status");
  const statusBody = document.getElementById("status-body");
  const verifyBtn = document.getElementById("verify");
  const declineBtn = document.getElementById("decline");
  const qrEl = document.getElementById("qr");
  const qrWrap = document.getElementById("qr-wrap");
  const deeplinkEl = document.getElementById("deeplink");
  const deeplinkDesktopEl = document.getElementById("deeplink-desktop");

  /** UI state machine. Each call replaces the visible status bar. */
  function setStatus(kind, text) {
    statusEl.classList.remove("hidden", "scanning", "exchanging", "ok", "err");
    if (kind) statusEl.classList.add(kind);
    statusBody.textContent = text;
  }
  function setStatusHTML(kind, html) {
    statusEl.classList.remove("hidden", "scanning", "exchanging", "ok", "err");
    if (kind) statusEl.classList.add(kind);
    statusBody.innerHTML = html;
  }
  function clearStatus() {
    statusEl.classList.add("hidden");
    statusEl.classList.remove("scanning", "exchanging", "ok", "err");
    statusBody.textContent = "";
  }

  function setDeepLinks(uri) {
    for (const a of [deeplinkEl, deeplinkDesktopEl]) {
      if (uri) {
        a.href = uri;
        a.removeAttribute("aria-disabled");
      } else {
        a.href = "#";
        a.setAttribute("aria-disabled", "true");
      }
    }
  }

  async function renderQR(text) {
    // Use the same `qrcode` library that @worldcoin/idkit (React) uses.
    const QRCode = (await import("https://esm.sh/qrcode@1.5.4")).default;
    const svg = await QRCode.toString(text, {
      type: "svg",
      margin: 1,
      width: 200,
      color: { dark: "#0a0a0c", light: "#ffffff" },
      errorCorrectionLevel: "M",
    });
    qrEl.classList.remove("qr-skeleton");
    qrEl.innerHTML = svg;
  }

  function setLoading(loading) {
    verifyBtn.disabled = loading;
    declineBtn.disabled = loading;
  }

  function resetUI() {
    qrEl.classList.add("qr-skeleton");
    qrEl.innerHTML = "";
    setDeepLinks(null);
    clearStatus();
    setLoading(false);
  }

  declineBtn.addEventListener("click", async () => {
    setLoading(true);
    try {
      await fetch("/decline", { method: "POST" });
      setStatus(
        "ok",
        "Got it -- Engram won't ask again. You can change your mind " +
        "later by asking your assistant to verify with World ID."
      );
    } catch (err) {
      setStatus("err", "Couldn't record decline: " + (err && err.message ? err.message : err));
      setLoading(false);
    }
  });

  async function startVerify() {
    setLoading(true);
    setStatus("scanning", "Loading IDKit...");
    let cfg;
    try {
      const cfgResp = await fetch("/idkit-config");
      if (!cfgResp.ok) {
        const text = await cfgResp.text();
        setStatus("err", "Couldn't fetch IDKit config (" + cfgResp.status + "): " + text);
        setLoading(false);
        return;
      }
      cfg = await cfgResp.json();
    } catch (err) {
      setStatus("err", "Couldn't reach engram-server: " + (err && err.message ? err.message : err));
      setLoading(false);
      return;
    }

    let request;
    try {
      const { IDKit, orbLegacy } = await import(
        "https://esm.sh/@worldcoin/idkit-core@4"
      );
      // Pass the page's own URL as `return_to` so a mobile user that
      // taps the deep link is bounced back here after verifying.
      request = await IDKit.request({
        app_id: cfg.app_id,
        action: cfg.action,
        rp_context: cfg.rp_context,
        allow_legacy_proofs: true,
        return_to: window.location.href,
      }).preset(orbLegacy());
    } catch (err) {
      setStatus("err", "Couldn't start IDKit: " + (err && err.message ? err.message : err));
      setLoading(false);
      return;
    }

    const uri = request.connectorURI;
    setDeepLinks(uri);
    try {
      await renderQR(uri);
    } catch (err) {
      // QR rendering shouldn't be fatal -- the deep link still works.
      console.error("QR render failed:", err);
    }
    setStatus(
      "scanning",
      "Waiting for World App... scan the QR code or tap " +
      "\\"Open in World App\\"."
    );

    let proof;
    try {
      proof = await request.pollUntilCompletion();
    } catch (err) {
      setStatusHTML(
        "err",
        "Verification failed: " + (err && err.message ? err.message : err) +
        "<br><a href=\\"#\\" id=\\"retry\\">Try again</a>."
      );
      document.getElementById("retry").addEventListener("click", (e) => {
        e.preventDefault();
        resetUI();
        startVerify();
      });
      return;
    }

    setStatus("exchanging", "Got proof -- exchanging it for an access token...");
    let ex;
    try {
      ex = await fetch("/proof", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(proof),
      });
    } catch (err) {
      setStatus("err", "Couldn't reach engram-server: " + (err && err.message ? err.message : err));
      setLoading(false);
      return;
    }
    if (!ex.ok) {
      const text = await ex.text();
      setStatusHTML(
        "err",
        "engram-server rejected the proof (" + ex.status + "): " + text +
        "<br><a href=\\"#\\" id=\\"retry\\">Try again</a>."
      );
      document.getElementById("retry").addEventListener("click", (e) => {
        e.preventDefault();
        resetUI();
        startVerify();
      });
      return;
    }
    setStatus("ok", "Verified! You can close this tab.");
  }

  verifyBtn.addEventListener("click", startVerify);
</script>
</body>
</html>
"""
