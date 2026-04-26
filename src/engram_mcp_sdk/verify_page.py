"""Static HTML for the localhost verification page.

Kept in its own module so it can be unit-tested without spinning up a server,
and so the JS lives in one easily-auditable place.

The page implements the IDKit UX recommended by World ID's [design
guidelines][dg] without pulling in React or the deprecated
`@worldcoin/idkit-standalone` package:

1. Auto-fetches the IDKit init payload (``app_id``, ``action``,
   ``rp_context``) from the local server, which proxies to engram-server.
2. Calls ``IDKit.request(...)`` from `@worldcoin/idkit-core` (loaded from
   esm.sh) to get a ``connectorURI`` -- a universal link that doubles as
   the QR-code payload (desktop) and a deep link into World App (mobile).
3. Renders the connector URI as a centered **QR code** (rendered with
   `qrcode` from esm.sh -- the same library used by ``@worldcoin/idkit``)
   and a prominent **"Open in World App"** button. Mobile user-agents see
   the deep-link button promoted above the QR code so a single tap
   launches World App without any scanning.
4. Polls for completion and walks through the status states recommended by
   IDKit's design guidelines (loading / scanning / exchanging / verified /
   error). On error, a "Try again" affordance re-runs the flow without a
   page reload.
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;600;700&family=Geist:wght@400;500;600&display=swap">
<style>
  :root {
    /* Engram landing palette (cream / ink / red). */
    --engram-cream: #fff1ef;
    --engram-cream-soft: #fff8f7;
    --engram-red: #ff3623;
    --engram-red-hover: #e52a18;
    --engram-ink: #1a1414;
    --engram-ink-70: rgba(26, 20, 20, 0.7);
    --engram-ink-55: rgba(26, 20, 20, 0.55);
    --engram-ink-45: rgba(26, 20, 20, 0.45);
    --engram-ink-15: rgba(26, 20, 20, 0.15);
    --engram-ink-10: rgba(26, 20, 20, 0.1);
    --engram-ink-06: rgba(26, 20, 20, 0.06);

    --bg-1: var(--engram-cream);
    --card: var(--engram-cream-soft);
    --card-border: var(--engram-ink-10);
    --hairline: var(--engram-ink-10);
    --fg: var(--engram-ink);
    --muted: var(--engram-ink-70);
    --subtle: var(--engram-ink-55);
    --accent: var(--engram-red);
    --accent-hover: var(--engram-red-hover);
    --decline: var(--engram-ink-06);
    --decline-hover: rgba(26, 20, 20, 0.1);
    --ok: #1f9d55;
    --warn: #c47500;
    --err: var(--engram-red);
    --link: var(--engram-red);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    font-family: "Geist", -apple-system, BlinkMacSystemFont, "Inter",
      "Segoe UI", Roboto, sans-serif;
    margin: 0;
    background:
      radial-gradient(900px 500px at 50% -120px,
        rgba(255, 54, 35, 0.16) 0%, transparent 60%),
      radial-gradient(600px 400px at 50% 120%,
        rgba(255, 54, 35, 0.08) 0%, transparent 60%),
      var(--bg-1);
    color: var(--fg);
    display: flex;
    min-height: 100vh;
    align-items: center;
    justify-content: center;
    padding: 24px;
    -webkit-font-smoothing: antialiased;
  }
  .card {
    width: 380px;
    max-width: 100%;
    background: var(--card);
    border: 1px solid var(--card-border);
    border-radius: 20px;
    padding: 28px 24px 22px;
    box-shadow:
      0 24px 60px rgba(26, 20, 20, 0.08),
      0 2px 6px rgba(26, 20, 20, 0.04);
    text-align: center;
  }
  .brand {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px 6px 8px;
    margin-bottom: 18px;
    border: 1px solid var(--card-border);
    border-radius: 999px;
    background: var(--engram-cream);
    color: var(--muted);
    font-size: 12px;
    letter-spacing: 0.02em;
  }
  .brand svg { display: block; }
  .brand .logo { color: var(--engram-red); }
  .brand .sep { color: var(--subtle); }
  .brand .who { color: var(--engram-ink); font-weight: 600; }
  h1 {
    font-family: "Bricolage Grotesque", "Geist", -apple-system,
      BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    font-size: 22px;
    margin: 0 0 6px;
    font-weight: 600;
    letter-spacing: -0.015em;
    color: var(--engram-ink);
  }
  p.lead {
    margin: 0 auto 22px;
    color: var(--muted);
    line-height: 1.55;
    font-size: 13.5px;
    max-width: 320px;
  }
  /* QR slot. Always reserves the same square so the layout doesn't jump
     between the loading skeleton and the rendered QR. */
  .qr-frame {
    width: 232px;
    height: 232px;
    margin: 0 auto 16px;
    background: #ffffff;
    border-radius: 14px;
    padding: 16px;
    box-shadow:
      0 12px 30px rgba(26, 20, 20, 0.08),
      0 0 0 1px var(--engram-ink-10);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .qr-frame > * {
    display: block;
    width: 200px !important;
    height: 200px !important;
  }
  .qr-skeleton {
    border-radius: 8px;
    background: linear-gradient(
      90deg,
      #f2e4e1 0%, #fff8f7 50%, #f2e4e1 100%
    );
    background-size: 200% 100%;
    animation: shimmer 1.4s linear infinite;
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .qr-caption {
    color: var(--muted);
    font-size: 12.5px;
    margin: 0 0 16px;
  }
  .qr-caption strong { color: var(--engram-ink); font-weight: 600; }
  .deeplink {
    display: block;
    text-align: center;
    text-decoration: none;
    background: var(--accent);
    color: var(--engram-cream);
    font-weight: 600;
    font-size: 13.5px;
    padding: 11px 14px;
    border-radius: 10px;
    margin-bottom: 10px;
    transition: background 0.12s ease, color 0.12s ease,
      border-color 0.12s ease;
  }
  .deeplink:hover { background: var(--accent-hover); }
  .deeplink[aria-disabled="true"] {
    opacity: 0.5;
    pointer-events: none;
    background: var(--decline);
    color: var(--engram-ink-55);
  }
  .deeplink-secondary {
    background: transparent;
    color: var(--engram-red);
    border: 1px solid rgba(255, 54, 35, 0.5);
  }
  .deeplink-secondary:hover {
    background: var(--accent);
    color: var(--engram-cream);
    border-color: var(--accent);
  }
  .decline {
    display: block;
    width: 100%;
    background: transparent;
    color: var(--subtle);
    border: 0;
    cursor: pointer;
    font-weight: 500;
    font-size: 13px;
    padding: 8px 14px;
    margin-top: 6px;
    font-family: inherit;
    border-radius: 8px;
    transition: color 0.12s ease, background 0.12s ease;
  }
  .decline:hover { color: var(--fg); background: var(--decline); }
  .decline:disabled { opacity: 0.4; cursor: not-allowed; }
  .status {
    margin: 14px auto 0;
    padding: 10px 12px;
    border-radius: 10px;
    background: var(--engram-cream);
    border: 1px solid var(--hairline);
    font-size: 12.5px;
    color: var(--muted);
    line-height: 1.5;
    display: flex;
    align-items: center;
    gap: 10px;
    text-align: left;
  }
  .status.hidden { display: none; }
  .status .dot {
    flex-shrink: 0;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--subtle);
  }
  .status.scanning .dot,
  .status.loading .dot {
    background: var(--accent);
    animation: pulse 1.2s ease-in-out infinite;
  }
  .status.exchanging .dot {
    background: var(--warn);
    animation: pulse 1.2s ease-in-out infinite;
  }
  .status.ok .dot { background: var(--ok); }
  .status.err .dot { background: var(--err); }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(255, 54, 35, 0.55); }
    70%  { box-shadow: 0 0 0 6px rgba(255, 54, 35, 0); }
    100% { box-shadow: 0 0 0 0 rgba(255, 54, 35, 0); }
  }
  .status .body { flex: 1; }
  .status a {
    color: var(--link);
    text-decoration: none;
    font-weight: 600;
  }
  .status a:hover { text-decoration: underline; }
  .footer {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--hairline);
    color: var(--subtle);
    font-size: 11.5px;
  }
  .footer a {
    color: var(--muted);
    text-decoration: none;
  }
  .footer a:hover {
    color: var(--fg);
    text-decoration: underline;
  }
  .hide-on-mobile { display: block; }
  .show-on-mobile { display: none; }
  @media (max-width: 480px) {
    .hide-on-mobile { display: none; }
    .show-on-mobile { display: block; }
    .card { padding: 24px 18px 18px; }
  }
</style>
</head>
<body>
<div class="card" role="main" aria-labelledby="title">
  <div class="brand" aria-hidden="true">
    <svg class="logo" width="16" height="16" viewBox="0 0 22 22"
         fill="currentColor">
      <circle cx="11" cy="3" r="2.4"/>
      <circle cx="3" cy="19" r="2.4"/>
      <circle cx="19" cy="19" r="2.4"/>
      <path d="M11 8.4c-1.8 0-3.3 1.4-3.3 3.2 0 1.7 1.5 3.2 3.3 3.2 1.8 0 3.3-1.5 3.3-3.2 0-1.8-1.5-3.2-3.3-3.2Zm-7.7 5.2 2.7 4.5c.6 1 2 1.4 3 .8.7-.4 1.1-1 1.2-1.7l-2-3.4-3.4-1.1c-.6.2-1.2.5-1.5 1Zm15.4 0c-.3-.5-.9-.8-1.5-1l-3.4 1.1-2 3.4c.1.7.5 1.3 1.2 1.7 1 .6 2.4.2 3-.8l2.7-4.4Zm-3-7.4c-.4-.7-1-1.1-1.7-1.2L11 7l1 3.6c.6.4 1.4.5 2 .1 1-.6 1.4-1.9.8-2.9l-1-1.6Zm-7.4 0L7.3 8c-.6 1-.2 2.3.8 2.9.6.4 1.4.3 2-.1L11 7 9.4 5C8.7 5.1 8 5.5 7.6 6.2Z"/>
    </svg>
    <span class="who">Engram</span>
    <span class="sep">×</span>
    <span class="who">World ID</span>
  </div>
  <h1 id="title">Connect your World ID</h1>
  <p class="lead">
    A one-time proof of personhood unlocks Engram's memory tools.
    Verify with World App and you'll never have to do it again on
    this machine.
  </p>

  <!-- Mobile: deep-link first; the QR is hidden because the user is
       already on their phone. -->
  <a id="deeplink" class="deeplink show-on-mobile" href="#"
     aria-disabled="true">Open in World App</a>

  <!-- Desktop: QR primary, deep-link as a secondary fallback below. -->
  <div class="qr-frame hide-on-mobile">
    <div id="qr" class="qr-skeleton" aria-label="QR code for World App"></div>
  </div>
  <p class="qr-caption hide-on-mobile">
    Scan with <strong>World App</strong> on your phone
  </p>
  <a id="deeplink-desktop" class="deeplink deeplink-secondary hide-on-mobile"
     href="#" aria-disabled="true">
    Or open in World App on this device
  </a>

  <button class="decline" id="decline" type="button">I'd rather not</button>

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
  const declineBtn = document.getElementById("decline");
  const qrEl = document.getElementById("qr");
  const deeplinkEl = document.getElementById("deeplink");
  const deeplinkDesktopEl = document.getElementById("deeplink-desktop");

  /** UI state machine. Each call replaces the visible status bar. */
  function setStatus(kind, text) {
    statusEl.classList.remove(
      "hidden", "loading", "scanning", "exchanging", "ok", "err"
    );
    if (kind) statusEl.classList.add(kind);
    statusBody.textContent = text;
  }
  function setStatusHTML(kind, html) {
    statusEl.classList.remove(
      "hidden", "loading", "scanning", "exchanging", "ok", "err"
    );
    if (kind) statusEl.classList.add(kind);
    statusBody.innerHTML = html;
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
      margin: 0,
      width: 200,
      color: { dark: "#1a1414", light: "#ffffff" },
      errorCorrectionLevel: "M",
    });
    qrEl.classList.remove("qr-skeleton");
    qrEl.innerHTML = svg;
  }

  function resetUI() {
    qrEl.classList.add("qr-skeleton");
    qrEl.innerHTML = "";
    setDeepLinks(null);
    declineBtn.disabled = false;
  }

  declineBtn.addEventListener("click", async () => {
    declineBtn.disabled = true;
    try {
      await fetch("/decline", { method: "POST" });
      setStatus(
        "ok",
        "Got it -- Engram won't ask again. You can change your mind " +
        "later by asking your assistant to verify with World ID."
      );
    } catch (err) {
      setStatus(
        "err",
        "Couldn't record decline: " +
        (err && err.message ? err.message : err)
      );
      declineBtn.disabled = false;
    }
  });

  async function startVerify() {
    setStatus("loading", "Loading World ID...");
    let cfg;
    try {
      const cfgResp = await fetch("/idkit-config");
      if (!cfgResp.ok) {
        const text = await cfgResp.text();
        setStatus(
          "err",
          "Couldn't fetch IDKit config (" + cfgResp.status + "): " + text
        );
        return;
      }
      cfg = await cfgResp.json();
    } catch (err) {
      setStatus(
        "err",
        "Couldn't reach engram-server: " +
        (err && err.message ? err.message : err)
      );
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
      setStatus(
        "err",
        "Couldn't start IDKit: " +
        (err && err.message ? err.message : err)
      );
      return;
    }

    const uri = request.connectorURI;
    setDeepLinks(uri);
    try {
      await renderQR(uri);
    } catch (err) {
      // QR rendering failure shouldn't be fatal -- the deep link still
      // works, so just log and keep going.
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
        "Verification failed: " +
        (err && err.message ? err.message : err) +
        ' &middot; <a href="#" id="retry">Try again</a>'
      );
      document.getElementById("retry").addEventListener("click", (e) => {
        e.preventDefault();
        resetUI();
        startVerify();
      });
      return;
    }

    setStatus(
      "exchanging",
      "Got proof -- exchanging it for an access token..."
    );
    let ex;
    try {
      ex = await fetch("/proof", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(proof),
      });
    } catch (err) {
      setStatus(
        "err",
        "Couldn't reach engram-server: " +
        (err && err.message ? err.message : err)
      );
      return;
    }
    if (!ex.ok) {
      const text = await ex.text();
      setStatusHTML(
        "err",
        "engram-server rejected the proof (" + ex.status + "): " + text +
        ' &middot; <a href="#" id="retry">Try again</a>'
      );
      document.getElementById("retry").addEventListener("click", (e) => {
        e.preventDefault();
        resetUI();
        startVerify();
      });
      return;
    }
    declineBtn.disabled = true;
    setStatus("ok", "Verified! You can close this tab.");
  }

  // Auto-start on page load -- there's no reason to make the user click
  // "Verify" first when they got here for exactly that.
  startVerify();
</script>
</body>
</html>
"""
