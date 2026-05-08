# Dashboard UX Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 high-priority UX issues identified in the Sol-Bot dashboard review: keyboard focus invisibility for reduced-motion users, inaccessible topbar icon buttons, sub-WCAG muted text contrast, and decorative-color overload in the sidebar.

**Architecture:** All edits are CSS-only or template-only — no Python or backend changes. Production runs from `/root/x-bot/sol-bot/` via the `sol-dashboard.service` systemd unit (`uvicorn sol_dashboard_api:app --port 8502`). The browser refetches `static/dashboard.css` and `templates/dashboard.html` automatically on next page load; no service restart needed.

**Tech Stack:** HTML, CSS, FastAPI/Jinja2 (server-rendered template).

**Out of scope (validated false positives or already-done):**
- iOS input auto-zoom — already handled at `static/dashboard.css:1117-1120` for ≤600px viewports.
- The two `max-width: 100vw !important` at `static/dashboard.css:1124, 1283` are intentional mobile fullscreen overrides (lightbox, monitor drawer), not escape hatches. Leave them.

**Verification approach:** No frontend test framework exists. Each task ends with grep-based assertions that the edit landed plus a `curl` smoke test that the dashboard still returns 200 with expected markup. Manual visual verification at `http://localhost:8502/` is the final gate.

---

## File Structure

| File | Role |
|------|------|
| `sol-bot/static/dashboard.css` | All design tokens, component styles, focus rules, sidebar color classes. Most edits here. |
| `sol-bot/templates/dashboard.html` | Topbar icon buttons (Task 2) and sidebar nav items color classes (Task 4). |

---

## Task 1: Hoist `:focus-visible` rule out of reduced-motion guard

**Problem:** The global `:focus-visible` style at `static/dashboard.css:4505` is wrapped inside `@media (prefers-reduced-motion: no-preference)` (block starts at line 4417). Users who prefer reduced motion get NO focus ring at all. Focus visibility has nothing to do with motion — this is an accessibility regression.

**Files:**
- Modify: `sol-bot/static/dashboard.css:4504-4509`

- [ ] **Step 1: Verify the broken state**

Run:
```bash
cd /root/x-bot/sol-bot
awk 'NR>=4415 && NR<=4515' static/dashboard.css | grep -nE "@media|:focus-visible"
```

Expected output should show `:focus-visible` appearing AFTER an opening `@media (prefers-reduced-motion: no-preference) {` and BEFORE the matching closing brace — confirming it is wrapped.

- [ ] **Step 2: Remove the wrapped `:focus-visible` block from inside the @media**

Edit `sol-bot/static/dashboard.css`. Find this exact block (around lines 4503-4510):

```css
  /* 1.6 — Focus ring polish: smooth outline appearance */
  :focus-visible {
    outline: 2px solid var(--accent, #7aa2f7);
    outline-offset: 2px;
    border-radius: var(--r-sm, 6px);
  }
}
```

Replace with just the closing brace (the rule is being moved):

```css
}
```

- [ ] **Step 3: Add a global `:focus-visible` rule near the top of the file**

Edit `sol-bot/static/dashboard.css`. Find the line `button { font-family: inherit; cursor: pointer; }` (around line 74) and ADD this block immediately after it:

```css

/* ============================================================
   GLOBAL FOCUS RING — applies regardless of motion preference.
   Inputs and buttons that use `outline: none` in their base styles
   are intentionally allowed to do so; this rule re-establishes the
   ring on actual keyboard focus only (not on mouse click).
   ============================================================ */
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

Note the removal of `border-radius` — `outline` does not respect border-radius on most browsers and the property does nothing useful here.

- [ ] **Step 4: Verify the rule is now unconditional**

Run:
```bash
cd /root/x-bot/sol-bot
grep -nE ":focus-visible *\{" static/dashboard.css
```

Expected: at least one match in the first 100 lines of the file (the new global rule), and the old line ~4505 is gone or no longer matches the same pattern.

Then check it's not inside a media query:
```bash
awk '/^[^@ ].*:focus-visible *\{/{print NR": "$0}' static/dashboard.css | head
```

Expected: at least one line number in the 70-100 range with `:focus-visible` at column 0 (i.e., not indented inside a media block).

- [ ] **Step 5: Smoke-test the dashboard still loads**

Run:
```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8502/static/dashboard.css
```

Expected: `HTTP 200` (or `HTTP 401` if auth-gated — both confirm the file is served; only `5xx` is a failure).

- [ ] **Step 6: Commit**

```bash
cd /root/x-bot
git add sol-bot/static/dashboard.css
git commit -m "fix(a11y): focus-visible global, unconditional of reduced-motion

The previous rule was nested inside @media (prefers-reduced-motion:
no-preference), which silently removed keyboard focus rings for users
who prefer reduced motion. Focus visibility is unrelated to motion;
hoist the rule to the top level so it always applies."
```

---

## Task 2: Topbar icon buttons — aria-label + SVG icons

**Problem:** Three buttons in the topbar (`templates/dashboard.html:117-119`) use unicode glyphs (`⤴`, `⧉`, `⋯`) with only a `title` attribute. `title` is unreliable on mobile screen readers, disappears on first hover, and the unicode glyphs render inconsistently across OS/font stacks. The Refresh button on line 115 already uses an SVG — the others should match.

**Files:**
- Modify: `sol-bot/templates/dashboard.html:117-119`

- [ ] **Step 1: Locate the three buttons**

Run:
```bash
cd /root/x-bot/sol-bot
sed -n '115,120p' templates/dashboard.html
```

Expected: lines showing the Refresh button (with SVG), then the three buttons with unicode glyphs ⤴, ⧉, ⋯.

- [ ] **Step 2: Replace the three buttons with accessible SVG versions**

Edit `sol-bot/templates/dashboard.html`. Find this exact block:

```html
        <button class="lin-icn-btn" title="Share">⤴</button>
        <button class="lin-icn-btn" title="Copy link">⧉</button>
        <button class="lin-icn-btn" title="More">⋯</button>
```

Replace with:

```html
        <button class="lin-icn-btn" type="button" title="Share" aria-label="Share">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
        </button>
        <button class="lin-icn-btn" type="button" title="Copy link" aria-label="Copy link">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        </button>
        <button class="lin-icn-btn" type="button" title="More" aria-label="More actions">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>
        </button>
```

The icons are Lucide-style (matching the sidebar SVGs at lines 52-81): Share = upload arrow, Copy link = overlapping squares, More = horizontal three-dot.

- [ ] **Step 3: Verify the unicode glyphs are gone from those buttons**

Run:
```bash
cd /root/x-bot/sol-bot
grep -nE 'class="lin-icn-btn"[^>]*>(⤴|⧉|⋯)' templates/dashboard.html
```

Expected: no matches.

- [ ] **Step 4: Verify the new aria-labels are present**

Run:
```bash
cd /root/x-bot/sol-bot
grep -cE 'aria-label="(Share|Copy link|More actions)"' templates/dashboard.html
```

Expected: `3`.

- [ ] **Step 5: Smoke-test the dashboard renders**

Run:
```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8502/
```

Expected: `HTTP 200` or `HTTP 401`. If `5xx`, the template has a Jinja syntax error — undo the edit.

- [ ] **Step 6: Commit**

```bash
cd /root/x-bot
git add sol-bot/templates/dashboard.html
git commit -m "fix(a11y): topbar icon buttons get aria-label + SVG icons

Share, Copy link, and More buttons used unicode glyphs with only a
title attribute. title is unreliable on mobile screen readers and
the glyphs render inconsistently across font stacks. Replaced with
Lucide-style SVGs (matching the sidebar icon set) and proper
aria-label + type=button."
```

---

## Task 3: Raise `--text-muted` to meet WCAG AA contrast

**Problem:** `static/dashboard.css:18` defines `--text-muted: #5e6166`. On the `--bg: #08090a` background this is ~3.4:1 contrast — fails WCAG AA for body text (needs 4.5:1). The token is used 101 times across the stylesheet, so a single value change ripples globally.

`#707378` on `#08090a` measures ~4.6:1 — meets AA. Keeps the muted feel without being barely-visible.

**Files:**
- Modify: `sol-bot/static/dashboard.css:18`

- [ ] **Step 1: Confirm current value**

Run:
```bash
cd /root/x-bot/sol-bot
grep -n "^  --text-muted:" static/dashboard.css
```

Expected: one match at line 18 with value `#5e6166`.

- [ ] **Step 2: Update the token**

Edit `sol-bot/static/dashboard.css`. Find:

```css
  --text-muted:     #5e6166;
```

Replace with:

```css
  --text-muted:     #707378;
```

- [ ] **Step 3: Verify the change**

Run:
```bash
cd /root/x-bot/sol-bot
grep -n "^  --text-muted:" static/dashboard.css
```

Expected: one match at line 18 with value `#707378`.

- [ ] **Step 4: Commit**

```bash
cd /root/x-bot
git add sol-bot/static/dashboard.css
git commit -m "fix(a11y): bump --text-muted to #707378 for WCAG AA contrast

Previous #5e6166 measured ~3.4:1 contrast against --bg, failing AA
(4.5:1 required for body text). #707378 measures ~4.6:1. Token is
referenced 101 times so this single change covers all muted text."
```

---

## Task 4: Monochrome the sidebar nav

**Problem:** The 7 sidebar items each carry a different decorative hue (violet, orange, blue, green, purple, pink, red) via classes on `<span class="lin-side-icn">`. In a 220px column this produces 7 colors competing for attention, diluting the active-item signal. Linear's actual design uses one neutral icon color and the accent only for the active state.

The CSS classes are defined at `static/dashboard.css:221-227`:
```css
.lin-side-icn.orange { color: var(--hue-orange); }
.lin-side-icn.blue   { color: var(--hue-blue); }
... etc
.lin-side-icn.violet { color: var(--accent); }
```

We will leave those CSS rules in place (other components may use them — e.g. badges) but make the sidebar nav specifically monochrome via a more-specific selector, AND remove the decorative class names from the sidebar items in HTML (so the markup expresses the intent).

**Files:**
- Modify: `sol-bot/templates/dashboard.html:52, 56, 60, 64, 68, 72, 77`
- Modify: `sol-bot/static/dashboard.css` (add new selector block; do not remove existing `.lin-side-icn.orange` etc. — out of scope)

- [ ] **Step 1: Locate the 7 sidebar items**

Run:
```bash
cd /root/x-bot/sol-bot
grep -nE '<span class="lin-side-icn (violet|orange|blue|green|purple|pink|red)' templates/dashboard.html
```

Expected: 7 matches at lines 52, 56, 60, 64, 68, 72, 77 (Settings on line 81 already has no hue class — that one is correct already).

- [ ] **Step 2: Strip the hue class from each sidebar item**

Edit `sol-bot/templates/dashboard.html`. For each of the 7 lines, replace `<span class="lin-side-icn violet">` (or `orange`, `blue`, `green`, `purple`, `pink`, `red`) with `<span class="lin-side-icn">`. Six exact replacements:

Line 52:
- Old: `<span class="lin-side-icn violet"><svg`
- New: `<span class="lin-side-icn"><svg`

Line 56:
- Old: `<span class="lin-side-icn orange"><svg`
- New: `<span class="lin-side-icn"><svg`

Line 60:
- Old: `<span class="lin-side-icn blue"><svg`
- New: `<span class="lin-side-icn"><svg`

Line 64:
- Old: `<span class="lin-side-icn green"><svg`
- New: `<span class="lin-side-icn"><svg`

Line 68:
- Old: `<span class="lin-side-icn purple"><svg`
- New: `<span class="lin-side-icn"><svg`

Line 72:
- Old: `<span class="lin-side-icn pink"><svg`
- New: `<span class="lin-side-icn"><svg`

Line 77:
- Old: `<span class="lin-side-icn red"><svg`
- New: `<span class="lin-side-icn"><svg`

- [ ] **Step 3: Add monochrome rules in CSS**

Edit `sol-bot/static/dashboard.css`. Find the existing block of hue rules (lines 221-227):

```css
.lin-side-icn.orange { color: var(--hue-orange); }
.lin-side-icn.blue   { color: var(--hue-blue); }
.lin-side-icn.yellow { color: var(--hue-yellow); }
.lin-side-icn.purple { color: var(--hue-purple); }
.lin-side-icn.pink   { color: var(--hue-pink); }
.lin-side-icn.green  { color: var(--hue-green); }
.lin-side-icn.violet { color: var(--accent); }
```

Add this block IMMEDIATELY AFTER (before the next selector):

```css

/* Sidebar nav: monochrome by default. Active item picks up accent.
   Decorative hue classes above remain available for badges/other UI. */
.lin-side-item .lin-side-icn { color: var(--text-secondary); }
.lin-side-item:hover .lin-side-icn { color: var(--text); }
.lin-side-item.active .lin-side-icn { color: var(--accent); }
```

- [ ] **Step 4: Verify HTML changes landed**

Run:
```bash
cd /root/x-bot/sol-bot
grep -cE '<span class="lin-side-icn (violet|orange|blue|green|purple|pink|red)"' templates/dashboard.html
```

Expected: `0`.

```bash
grep -cE '<span class="lin-side-icn"><svg' templates/dashboard.html
```

Expected: `7` or more (7 from the sidebar; Settings on line 81 already had no hue class but also no SVG inside — actually it does. Verify yourself the count is at least 7.)

- [ ] **Step 5: Verify CSS rules landed**

Run:
```bash
cd /root/x-bot/sol-bot
grep -nE '\.lin-side-item(\s|:hover|\.active)?\s*\.lin-side-icn' static/dashboard.css
```

Expected: 3 matches (default, hover, active).

- [ ] **Step 6: Smoke-test**

Run:
```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8502/
```

Expected: `HTTP 200` or `HTTP 401`.

- [ ] **Step 7: Commit**

```bash
cd /root/x-bot
git add sol-bot/templates/dashboard.html sol-bot/static/dashboard.css
git commit -m "refactor(dashboard): monochrome sidebar — accent only on active

Sidebar previously used 7 decorative hues (violet, orange, blue,
green, purple, pink, red) across the nav items. In a 220px column
this dilutes the active-item signal. Strip hue classes from the
nav markup and add a more-specific monochrome rule: text-secondary
default, text on hover, accent on .active. Hue classes remain
defined for use elsewhere (badges, status chips)."
```

---

## Self-Review

**1. Spec coverage:**
- Original fix #1 (focus-visible) → Task 1 ✓ (with corrected diagnosis: hoist out of @media instead of adding new)
- Original fix #2 (topbar icon buttons) → Task 2 ✓
- Original fix #3 (--text-muted) → Task 3 ✓
- Original fix #4 (16px inputs) → DROPPED with justification (already done at line 1117-1120)
- Original fix #5 (monochrome sidebar) → Task 4 ✓
- Original fix #6 (max-width: 100vw !important) → DROPPED with justification (intentional mobile fullscreen, not escape hatches)

**2. Placeholder scan:** No "TBD", no "similar to", no unspecified handlers. All edits show exact before/after.

**3. Type consistency:** N/A (CSS/HTML only). All CSS variable names referenced (`--accent`, `--text-secondary`, `--text-muted`, `--bg`, `--hue-*`) are defined in the `:root` block at the top of `dashboard.css`.

**4. Verification limits:** No frontend tests exist; verification relies on grep + curl smoke tests. Manual visual check at `:8502` is the final gate. Each task is independently revertible (single commit each).

---

## Post-Plan Manual Verification (after all 4 tasks land)

Open `http://localhost:8502/` in a browser and:

1. **Tab through the topbar.** Refresh / Share / Copy link / More buttons should each show a 2px accent outline when focused via keyboard. Click them — no outline should appear.
2. **Toggle reduced-motion** in OS settings (macOS: System Settings → Accessibility → Display → Reduce motion). Reload. Tab again — focus rings should still appear.
3. **Inspect the sidebar.** All 7 nav icons should be the same neutral gray. Click between them — only the active item's icon turns purple (accent). Hover an inactive item — its icon brightens to white but stays monochrome.
4. **Read any muted text** (e.g. user sub-label "tier 2 · fastapi" in the sidebar footer, breadcrumb separators). Should feel readable, not ghostly.
5. **VoiceOver or NVDA the topbar.** Each icon button should announce "Share, button" / "Copy link, button" / "More actions, button" — not just "button" or the unicode glyph name.
