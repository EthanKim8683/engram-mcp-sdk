"""Static HTML for the localhost verification page.

Kept in its own module so it can be unit-tested without spinning up a server,
and so the JS lives in one easily-auditable place. The page:

1. Fetches IDKit init config (``app_id``, ``action``, ``rp_context``) from
   the local server, which proxies to engram-server.
2. Calls ``IDKit.request(...)`` with that config and renders a "Open in
   World App" link plus a QR code.
3. Polls for completion, then POSTs the proof to ``/proof`` (which forwards
   it to engram-server and persists the resulting access token).
4. If the user clicks "I'd rather not", POSTs to ``/decline`` instead so the
   SDK remembers their preference.

The page is intentionally dependency-free at server start time -- everything
loads from CDNs at runtime so we don't bundle JS.
"""

VERIFY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Engram - World ID verification</title>
<style>
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      sans-serif;
    margin: 0;
    background: #0e0e10;
    color: #e6e6e6;
    display: flex;
    min-height: 100vh;
    align-items: center;
    justify-content: center;
  }
  .card {
    width: 420px;
    max-width: calc(100% - 32px);
    background: #1a1a1d;
    border: 1px solid #2a2a2e;
    border-radius: 12px;
    padding: 28px;
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.4);
  }
  h1 { font-size: 18px; margin: 0 0 8px; }
  p { line-height: 1.5; color: #b3b3b8; }
  .row { display: flex; gap: 12px; margin-top: 20px; }
  button {
    flex: 1;
    padding: 12px;
    border-radius: 8px;
    border: 0;
    font-weight: 600;
    cursor: pointer;
    font-size: 14px;
  }
  .verify { background: #4f46e5; color: white; }
  .decline { background: #2a2a2e; color: #d6d6d6; }
  button:disabled { opacity: 0.5; cursor: progress; }
  #status {
    margin-top: 20px;
    padding: 12px;
    border-radius: 8px;
    background: #0b0b0d;
    border: 1px solid #2a2a2e;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    color: #9aa0a6;
    word-break: break-all;
    min-height: 1.4em;
  }
  a { color: #93c5fd; }
</style>
</head>
<body>
<div class="card">
  <h1>Engram requires a World ID verification</h1>
  <p>
    The Engram memory tools (<code>learn</code> and <code>recall</code>) are
    gated on a one-time proof of personhood. Verifying takes about
    20 seconds and you'll never have to do it again on this machine.
  </p>
  <div class="row">
    <button class="verify" id="verify">Verify with World ID</button>
    <button class="decline" id="decline">I'd rather not</button>
  </div>
  <div id="status"></div>
</div>
<script type="module">
  const statusEl = document.getElementById("status");
  const verifyBtn = document.getElementById("verify");
  const declineBtn = document.getElementById("decline");

  function setStatus(text) { statusEl.textContent = text; }
  function setStatusHTML(html) { statusEl.innerHTML = html; }

  declineBtn.addEventListener("click", async () => {
    declineBtn.disabled = true;
    verifyBtn.disabled = true;
    await fetch("/decline", { method: "POST" });
    setStatus(
      "Got it -- Engram won't ask again. You can change your mind later " +
      "by asking your assistant to verify with World ID."
    );
  });

  verifyBtn.addEventListener("click", async () => {
    verifyBtn.disabled = true;
    declineBtn.disabled = true;
    setStatus("Loading IDKit...");
    try {
      const cfg = await fetch("/idkit-config").then((r) => {
        if (!r.ok) throw new Error("Failed to fetch idkit config: " + r.status);
        return r.json();
      });
      const { IDKit, orbLegacy } = await import(
        "https://esm.sh/@worldcoin/idkit-core@4"
      );
      setStatus("Opening World App...");
      const request = await IDKit.request({
        app_id: cfg.app_id,
        action: cfg.action,
        rp_context: cfg.rp_context,
        allow_legacy_proofs: true,
      }).preset(orbLegacy());
      setStatusHTML(
        '<div>Open in World App: ' +
        '<a href="' + request.connectorURI + '" target="_blank">' +
        request.connectorURI + "</a></div>"
      );
      const proof = await request.pollUntilCompletion();
      setStatus("Got proof, exchanging for access token...");
      const ex = await fetch("/proof", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(proof),
      });
      if (!ex.ok) {
        const text = await ex.text();
        setStatus("Verification failed server-side: " + text);
        verifyBtn.disabled = false;
        declineBtn.disabled = false;
        return;
      }
      setStatus("Verified! You can close this tab.");
    } catch (err) {
      setStatus("Verification error: " + (err && err.message ? err.message : err));
      verifyBtn.disabled = false;
      declineBtn.disabled = false;
    }
  });
</script>
</body>
</html>
"""
