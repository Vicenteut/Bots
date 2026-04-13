/**
 * gdelt_spike_runner.js
 * Promptfoo file:// provider — must export a class with callApi method.
 * promptfoo instantiates: new Provider(options) then calls provider.callApi(prompt)
 */

const { detectSpike } = require('./gdelt_spike_logic');

class GdeltSpikeProvider {
  constructor(options) {}

  id() {
    return 'gdelt-spike-detector';
  }

  async callApi(prompt) {
    const input = JSON.parse(prompt);

    const lastAlert = (input.lastAlert === 'null' || input.lastAlert === null)
      ? null
      : input.lastAlert;

    const now = input.nowISO ? new Date(input.nowISO) : new Date();

    const result = detectSpike(
      parseInt(input.currentCount, 10),
      parseInt(input.baselineCount, 10),
      lastAlert,
      now
    );

    return { output: JSON.stringify(result) };
  }
}

module.exports = GdeltSpikeProvider;
