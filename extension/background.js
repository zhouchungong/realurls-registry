/**
 * Realurls browser extension — background service worker.
 *
 * 隐私设计：每天从 api.realurls.org 拉一次 domains.json（几十 KB），之后**所有判定在本机完成**，
 * 不会把你访问的域名发给任何服务器。弹窗里的"查证据"是你主动点击才会打开网页。
 *
 * 只做三件事：
 *   verified 域名   → 工具栏图标显示绿色 ✓
 *   相似但未收录    → 图标显示 !，并让内容脚本在页面顶部弹一条提示（附真官网链接）
 *   其它            → 什么都不做。"不知道"就是不知道，不制造噪音。
 */

import { Resolver, registrableDomain } from "./resolve.mjs";

const API = "https://api.realurls.org";
const REFRESH_MINUTES = 24 * 60;

let resolver = null;

async function loadDataset(force = false) {
  const { dataset, fetchedAt } = await chrome.storage.local.get(["dataset", "fetchedAt"]);
  const fresh = dataset && fetchedAt && Date.now() - fetchedAt < REFRESH_MINUTES * 60 * 1000;
  if (!force && fresh) {
    resolver = new Resolver(dataset);
    return;
  }
  try {
    const [domains, manifest] = await Promise.all([
      fetch(`${API}/v1/domains.json`).then(r => r.json()),
      fetch(`${API}/v1/manifest`).then(r => r.json()),
    ]);
    // entities.json 不需要：扩展只做域名判定，不做名字查询
    const ds = { domains, entities: {}, manifest };
    await chrome.storage.local.set({ dataset: ds, fetchedAt: Date.now() });
    resolver = new Resolver(ds);
  } catch (e) {
    if (dataset) resolver = new Resolver(dataset);   // 离线时用旧数据，不报错
  }
}

function setBadge(tabId, text, color, title) {
  chrome.action.setBadgeText({ tabId, text });
  if (color) chrome.action.setBadgeBackgroundColor({ tabId, color });
  chrome.action.setTitle({ tabId, title });
}

async function checkTab(tabId, url) {
  if (!resolver) await loadDataset();
  if (!resolver || !/^https?:/i.test(url)) return;
  const domain = registrableDomain(url);
  const r = resolver.resolve(domain);

  if (r.verdict === "official") {
    setBadge(tabId, "✓", "#0a7d32", `Realurls: verified domain of ${r.entity.name}`);
  } else if (r.verdict === "not_official") {
    setBadge(tabId, "!", "#9a3412", `Realurls: not a known domain of ${r.looks_like.name}`);
    const { dismissed = {} } = await chrome.storage.session.get("dismissed");
    if (!dismissed[domain]) {
      chrome.tabs.sendMessage(tabId, {
        type: "realurls:lookalike", domain,
        looks_like: r.looks_like.name, official_domains: r.official_domains,
        evidence_url: `https://realurls.org/e/${r.looks_like.id.replace(/^org:/, "")}`,
      }).catch(() => {});
    }
  } else {
    setBadge(tabId, "", null, "Realurls: no verdict for this domain");
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("refresh", { periodInMinutes: REFRESH_MINUTES });
  loadDataset(true);
});
chrome.runtime.onStartup.addListener(() => loadDataset());
chrome.alarms.onAlarm.addListener(a => { if (a.name === "refresh") loadDataset(true); });

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" && tab.url) checkTab(tabId, tab.url);
});
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (tab?.url) checkTab(tabId, tab.url);
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg?.type === "realurls:dismiss") {
    chrome.storage.session.get("dismissed").then(({ dismissed = {} }) => {
      dismissed[msg.domain] = true;
      chrome.storage.session.set({ dismissed });
    });
  }
  if (msg?.type === "realurls:query") {
    (async () => {
      if (!resolver) await loadDataset();
      reply(resolver ? { ...resolver.resolve(msg.url), dataset_version: resolver.manifest.dataset_version } : { verdict: "unavailable" });
    })();
    return true;
  }
});
