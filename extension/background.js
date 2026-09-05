/**
 * Realurls browser extension — background service worker.
 *
 * Privacy: domains.json (tens of KB) is fetched from api.realurls.org once a day; after that every verdict
 * is computed locally. The domains you visit are never sent anywhere. "See evidence" opens a page only when you click it.
 *
 * It does exactly three things:
 *   verified domain          → green ✓ on the toolbar icon
 *   lookalike, not listed    → ! on the icon, and the content script shows a banner with the real official domains
 *   anything else            → nothing. "Don't know" means don't know; no noise.
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
    // entities.json is not needed: the extension only judges domains, it does not look up names
    const ds = { domains, entities: {}, manifest };
    await chrome.storage.local.set({ dataset: ds, fetchedAt: Date.now() });
    resolver = new Resolver(ds);
  } catch (e) {
    if (dataset) resolver = new Resolver(dataset);   // offline: keep the previous dataset, no error
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
