const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const status = document.getElementById("status");

chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
  if (!tab?.url || !/^https?:/i.test(tab.url)) { status.innerHTML = '<span class="muted">Not a web page.</span>'; return; }
  chrome.runtime.sendMessage({ type: "realurls:query", url: tab.url }, r => {
    if (!r || r.verdict === "unavailable") { status.innerHTML = '<span class="muted">Dataset not loaded yet — try again in a moment.</span>'; return; }
    const d = esc(r.domain);
    if (r.verdict === "official") {
      status.innerHTML = `<div class="d">${d}<span class="badge ok">verified</span></div><p>Official domain of <b>${esc(r.entity.name)}</b>.</p><p><a href="https://realurls.org/e/${esc(r.entity.id.replace(/^org:/, ""))}" target="_blank">See the evidence →</a></p>`;
    } else if (r.verdict === "not_official") {
      status.innerHTML = `<div class="d">${d}<span class="badge warn">not ${esc(r.looks_like.name)}</span></div><p>Resembles <b>${esc(r.looks_like.domain)}</b> but is not a verified domain of ${esc(r.looks_like.name)}.</p><p>Verified: ${r.official_domains.map(x => `<a href="https://${esc(x)}" target="_blank">${esc(x)}</a>`).join(" · ")}</p>`;
    } else if (r.verdict === "insufficient_evidence") {
      status.innerHTML = `<div class="d">${d}<span class="badge unk">${esc(r.status)}</span></div><p>Known entity (${esc(r.entity.name)}) but evidence is insufficient — not confirmed official.</p>`;
    } else {
      status.innerHTML = `<div class="d">${d}<span class="badge unk">no verdict</span></div><p class="muted">Not in the registry. That means "don't know", not "bad".</p>`;
    }
    status.innerHTML += `<p class="muted">dataset ${esc(r.dataset_version || "")}</p>`;
  });
});

document.getElementById("f").onsubmit = e => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (q) chrome.tabs.create({ url: `https://realurls.org/d/${encodeURIComponent(q)}` });
};
