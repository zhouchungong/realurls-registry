// 只在后台判定为"相似但未收录"时收到消息；其余页面这个脚本什么都不做。
chrome.runtime.onMessage.addListener(msg => {
  if (msg?.type !== "realurls:lookalike" || document.getElementById("realurls-banner")) return;

  const bar = document.createElement("div");
  bar.id = "realurls-banner";
  bar.setAttribute("role", "alert");
  bar.style.cssText = [
    "position:fixed", "top:0", "left:0", "right:0", "z-index:2147483647",
    "background:#fff1e6", "color:#9a3412", "border-bottom:2px solid #f59e0b",
    "font:15px/1.4 system-ui,-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif",
    "padding:10px 44px 10px 16px", "box-shadow:0 2px 8px rgba(0,0,0,.15)",
  ].join(";");

  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const officials = msg.official_domains.map(d => `<a href="https://${esc(d)}" style="color:#0b57d0;font-weight:600">${esc(d)}</a>`).join(" · ");
  bar.innerHTML = `<b>${esc(msg.domain)}</b> is <b>not</b> a known domain of <b>${esc(msg.looks_like)}</b>.
    Verified: ${officials}
    <a href="${esc(msg.evidence_url)}" style="color:#9a3412;margin-left:10px;text-decoration:underline">evidence</a>
    <span style="opacity:.75;margin-left:10px">（不是安全判定，只是归属提示）</span>
    <button id="realurls-close" aria-label="dismiss" style="position:absolute;right:10px;top:6px;border:0;background:transparent;font-size:20px;cursor:pointer;color:#9a3412">×</button>`;

  document.documentElement.appendChild(bar);
  document.getElementById("realurls-close").onclick = () => {
    bar.remove();
    chrome.runtime.sendMessage({ type: "realurls:dismiss", domain: msg.domain });
  };
});
