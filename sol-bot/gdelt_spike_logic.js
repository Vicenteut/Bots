/**
 * gdelt_spike_logic.js
 * Pure function for GDELT spike detection — no I/O, no side effects.
 * Used by promptfoo test suite and mirrored in the n8n Code node.
 *
 * @param {number} currentCount   - Articles found in last 30 min window
 * @param {number} baselineCount  - Stored rolling baseline count
 * @param {string|null} lastAlert - ISO timestamp of last alert (or null)
 * @param {Date} [now]            - Override "now" for deterministic testing (default: new Date())
 * @returns {{ spikePercent: number, inCooldown: boolean, shouldAlert: boolean }}
 */
function detectSpike(currentCount, baselineCount, lastAlert, now) {
  if (!now) now = new Date();

  const COOLDOWN_MS = 2 * 60 * 60 * 1000; // 2 hours
  const SPIKE_THRESHOLD_PCT = 200;
  const ABSOLUTE_THRESHOLD = 3; // min articles when baseline is 0 to consider a spike

  // Spike calculation
  let spikePercent = 0;
  if (baselineCount > 0) {
    spikePercent = ((currentCount - baselineCount) / baselineCount) * 100;
  } else if (currentCount > ABSOLUTE_THRESHOLD) {
    // Synthetic spike: no baseline but meaningful activity detected
    spikePercent = 300;
  }

  // Cooldown check
  let inCooldown = false;
  if (lastAlert) {
    const lastAlertTime = new Date(lastAlert).getTime();
    inCooldown = (now.getTime() - lastAlertTime) < COOLDOWN_MS;
  }

  const shouldAlert = spikePercent > SPIKE_THRESHOLD_PCT && !inCooldown;

  return {
    spikePercent: Math.round(spikePercent),
    inCooldown,
    shouldAlert
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { detectSpike };
}
