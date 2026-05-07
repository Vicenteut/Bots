/**
 * _interrupts.js — shared trash-edit pattern interrupts for Phase 1 templates.
 *
 * Templates include this via a <script src="_interrupts.js"></script> after GSAP
 * is loaded. Functions add tweens to a passed-in GSAP timeline.
 *
 * Hyperframes constraint: deterministic only. No Date.now(), no Math.random().
 */
(function (global) {
  /** Microcut: subtle scale punch on #bg at time t. The original "black flash"
   *  variant felt like a glitch/blink, so by default the flash is off. Pass
   *  opts.flashOpacity (0..1) to bring it back. */
  function microcut(tl, t, opts) {
    opts = opts || {};
    var flash = opts.flashSelector || "#cut-flash";
    var bg = opts.bgSelector || "#bg";
    var scaleTo = opts.scaleTo != null ? opts.scaleTo : 1.05;
    var flashOpacity = opts.flashOpacity != null ? opts.flashOpacity : 0;
    if (flashOpacity > 0) {
      tl.to(flash, { opacity: flashOpacity, duration: 0.04, ease: "power1.out" }, t);
      tl.to(flash, { opacity: 0, duration: 0.08, ease: "power1.in" }, t + 0.04);
    }
    tl.to(
      bg,
      { scale: scaleTo, duration: 0.12, yoyo: true, repeat: 1,
        ease: "power2.inOut", overwrite: "auto" },
      t,
    );
  }

  /** Background-only zoom punch (no stamp). Used at hard interrupt moments. */
  function bgPunch(tl, t, opts) {
    opts = opts || {};
    var bg = opts.bgSelector || "#bg";
    var peak = opts.peak != null ? opts.peak : 1.18;
    var rest = opts.rest != null ? opts.rest : 1.05;
    tl.to(bg, { scale: peak, duration: 0.4, ease: "back.out(2)" }, t);
    tl.to(bg, { scale: rest, duration: 0.4, ease: "power2.inOut" }, t + 0.4);
  }

  /** Slide-up + fade-out animation for a stamp-style element. Reusable for
   *  rehook stamps and per-beat stamps. opts.hold = seconds visible before
   *  fade-out (default 2.4). opts.fromY = enter y offset (default 200). */
  function stampPunch(tl, t, selector, opts) {
    opts = opts || {};
    var fromY = opts.fromY != null ? opts.fromY : 200;
    var hold = opts.hold != null ? opts.hold : 2.4;
    tl.fromTo(
      selector,
      { y: fromY, opacity: 0, scale: 0.92 },
      { y: 0, opacity: 1, scale: 1, duration: 0.4, ease: "back.out(2.4)" },
      t,
    );
    tl.to(selector, { opacity: 0, duration: 0.3, ease: "power2.in" }, t + 0.4 + hold);
  }

  /** Rehook punch at second 5: bg zooms + stamp slides up.
   *  Kept for backwards compat with templates that haven't migrated to the
   *  bgPunch + stampPunch combo yet. */
  function rehookPunch(tl, t, opts) {
    opts = opts || {};
    bgPunch(tl, t, opts);
    stampPunch(tl, t + 0.05, opts.stampSelector || "#rehook-stamp", { hold: 2.2 });
  }

  /** Freeze stamp: pause #bg video for `hold` seconds with a text overlay. */
  function freezeStamp(tl, t, hold, stampSelector) {
    tl.call(function () {
      var v = document.querySelector("#bg");
      if (v && typeof v.pause === "function") v.pause();
    }, [], t);
    tl.to(stampSelector, { opacity: 1, scale: 1.0, duration: 0.12 }, t);
    tl.to(stampSelector, { opacity: 0, duration: 0.2 }, t + hold);
    tl.call(function () {
      var v = document.querySelector("#bg");
      if (v && typeof v.play === "function") v.play();
    }, [], t + hold);
  }

  /** Color flash: full-screen colored div fades in/out at peak. */
  function colorFlash(tl, t, color) {
    var flash = "#color-flash";
    color = color || "rgba(255,40,40,0.55)";
    tl.set(flash, { backgroundColor: color }, t);
    tl.to(flash, { opacity: 0.55, duration: 0.06, ease: "power1.out" }, t);
    tl.to(flash, { opacity: 0, duration: 0.18, ease: "power1.in" }, t + 0.06);
  }

  /**
   * Karaoke captions: scale + color the active word.
   * words = [{word, start, end}, ...]
   * Container #karaoke holds <span data-i="N">word</span> elements (rendered server-side).
   * opts.offset (seconds) shifts all timestamps; pass the audio's data-start so
   * karaoke lines up with when the TTS actually starts playing in the timeline.
   */
  function karaoke(tl, words, opts) {
    if (!words || !words.length) return;
    opts = opts || {};
    var offset = opts.offset != null ? opts.offset : 0;
    words.forEach(function (w, i) {
      var sel = "#karaoke span[data-i=\"" + i + "\"]";
      tl.set(sel, { color: "#ffd500", scale: 1.15, opacity: 1.0 }, w.start + offset);
      tl.set(sel, { color: "#ffffff", scale: 1.0, opacity: 0.55 }, w.end + offset);
    });
  }

  /**
   * Rolling karaoke: show ~chunkSize words at a time (default 2). Each chunk
   * fades in at its first word's start, holds while every word inside it
   * gets a yellow + scale punch synced to whisper timestamps, then fades out
   * before the next chunk arrives.
   *
   * Server-side `_karaoke_html_chunked` emits `<div class="kchunk" data-c="N">
   *   <span class="kw" data-i="K">word</span> ...</div>` per chunk; all chunks
   * stack at the same absolute position so only one is visible at a time.
   *
   * opts.offset (s)  — shift for TTS data-start (e.g. 0.4)
   * opts.pad (s)     — pre-roll so highlight lands a hair early (default 0.04)
   * opts.chunkSize   — must match server-side chunk size (default 2)
   * opts.exitGap (s) — extra hold after last word before fade-out (default 0.10)
   */
  function karaokeRolling(tl, words, opts) {
    if (!words || !words.length) return;
    opts = opts || {};
    var offset = opts.offset != null ? opts.offset : 0;
    var pad = opts.pad != null ? opts.pad : 0.04;
    var chunkSize = opts.chunkSize || 2;
    var exitGap = opts.exitGap != null ? opts.exitGap : 0.10;

    var totalChunks = Math.ceil(words.length / chunkSize);

    // Hide every chunk at t=0 so nothing leaks before its turn.
    for (var c0 = 0; c0 < totalChunks; c0++) {
      tl.set('.kchunk[data-c="' + c0 + '"]', { opacity: 0, visibility: "hidden" }, 0);
    }

    for (var c = 0; c < totalChunks; c++) {
      var startIdx = c * chunkSize;
      var endIdx = Math.min(startIdx + chunkSize, words.length);
      var firstStart = words[startIdx].start + offset - pad;
      var lastEnd = words[endIdx - 1].end + offset + exitGap;
      var sel = '.kchunk[data-c="' + c + '"]';

      // Reveal chunk
      tl.set(sel, { visibility: "visible" }, firstStart);
      tl.fromTo(sel, { opacity: 0 }, { opacity: 1, duration: 0.10, ease: "power1.out" }, firstStart);

      // Per-word punch (yellow + scale up at start, white + scale down at end)
      for (var wi = startIdx; wi < endIdx; wi++) {
        var w = words[wi];
        var wsel = sel + ' .kw[data-i="' + wi + '"]';
        tl.fromTo(
          wsel,
          { color: "#ffffff", scale: 1.0 },
          { color: "#ffd500", scale: 1.12, duration: 0.10, ease: "back.out(2)" },
          w.start + offset - pad,
        );
        tl.to(
          wsel,
          { color: "#ffffff", scale: 1.0, duration: 0.18, ease: "power1.in" },
          w.end + offset,
        );
      }

      // Hide chunk before the next one shows
      tl.to(sel, { opacity: 0, duration: 0.10, ease: "power1.in" }, lastEnd);
      tl.set(sel, { visibility: "hidden" }, lastEnd + 0.01);  // CRITICAL: kill leak
    }
  }

  /**
   * CTA stamp: slide-in card distinct from the karaoke band so the closing
   * "Follow The Clam Letter" reads as a deliberate ask, not just another
   * highlighted word. Pairs with #cta-stamp div in the template (positioned
   * at y=1400 to stay above the IG/TikTok bottom UI safe zone).
   */
  function ctaStamp(tl, t, selector, opts) {
    opts = opts || {};
    var hold = opts.hold != null ? opts.hold : 1.5;
    var fromY = opts.fromY != null ? opts.fromY : 120;

    tl.fromTo(
      selector,
      { y: fromY, opacity: 0, scale: 0.85 },
      { y: 0, opacity: 1, scale: 1.0, duration: 0.35, ease: "back.out(2.6)" },
      t,
    );
    // small breathing pulse so the card draws the eye
    tl.to(selector, { scale: 1.05, duration: 0.14, ease: "power2.out" }, t + 0.45);
    tl.to(selector, { scale: 1.0, duration: 0.14, ease: "power2.in" }, t + 0.59);
    tl.to(selector, { opacity: 0, y: -30, duration: 0.30, ease: "power2.in" }, t + 0.35 + hold);
  }

  /**
   * Loop bridge: cross-fade last frame's hook block and the first frame's badge
   * during the final 1s, so the loop reads as continuous.
   */
  function loopBridge(tl, durationSec, opts) {
    opts = opts || {};
    var tStart = durationSec - 1.0;
    var hook = opts.hookSelector || "#hook";
    var badge = opts.badgeSelector || "#badge";
    tl.to(hook, { opacity: 0.15, duration: 0.6, ease: "power2.in" }, tStart);
    tl.fromTo(
      badge,
      { scale: 1, opacity: 1 },
      { scale: 0.55, opacity: 0.0, duration: 0.4, ease: "power2.in" },
      tStart + 0.4,
    );
  }

  global.SolInterrupts = {
    microcut: microcut,
    bgPunch: bgPunch,
    stampPunch: stampPunch,
    rehookPunch: rehookPunch,
    freezeStamp: freezeStamp,
    colorFlash: colorFlash,
    karaoke: karaoke,
    karaokeRolling: karaokeRolling,
    ctaStamp: ctaStamp,
    loopBridge: loopBridge,
  };
})(window);
