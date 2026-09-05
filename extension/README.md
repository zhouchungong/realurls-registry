# realurls browser extension

Warns you when a site *looks like* a well-known product's domain but is not verified as theirs — and tells you the verified one.

- **Ownership only, never safety.** A warning means "this is not the domain you probably meant", not "this is malware".
- **Private by design.** The extension downloads the signed dataset once a day and does every check **on your machine**. Your browsing never leaves your computer. Clicking "See the evidence" opens realurls.org — that is the only time it navigates anywhere.

## What it does

| you visit | toolbar badge | page |
|---|---|---|
| a verified domain (e.g. `ollama.com`) | green ✓ | nothing |
| a lookalike that is not theirs (e.g. `claude-desktop.io`) | orange ! | a dismissable banner naming the verified domains |
| anything else | no badge | nothing — "don't know" makes no noise |

## Install (unpacked, until the store listing is live)

1. `chrome://extensions` → enable **Developer mode**
2. **Load unpacked** → choose this `extension/` folder
3. Visit `https://ollama.com` — the badge should turn green

`resolve.mjs` here is a copy of `packages/core/resolve.mjs`; keep them in sync.

## Permissions

`storage` (cache the dataset), `alarms` (daily refresh), `tabs` (read the current tab's URL to set the badge), host permission for `api.realurls.org` only.
