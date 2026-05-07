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

  /** Rehook punch at second 5: bg zooms, rehook stamp slides up. */
  function rehookPunch(tl, t, opts) {
    opts = opts || {};
    var bg = opts.bgSelector || "#bg";
    var stamp = opts.stampSelector || "#rehook-stamp";
    tl.to(bg, { scale: 1.18, duration: 0.4, ease: "back.out(2)" }, t);
    tl.to(bg, { scale: 1.05, duration: 0.4, ease: "power2.inOut" }, t + 0.4);
    tl.fromTo(
      stamp,
      { y: 200, opacity: 0 },
      { y: 0, opacity: 1, duration: 0.35, ease: "back.out(2.4)" },
      t + 0.05,
    );
    tl.to(stamp, { opacity: 0, duration: 0.3, ease: "power2.in" }, t + 2.6);
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
    rehookPunch: rehookPunch,
    freezeStamp: freezeStamp,
    colorFlash: colorFlash,
    karaoke: karaoke,
    loopBridge: loopBridge,
  };
})(window);
