// Runs the shared tile-state scenarios against the browser's state machine.
import { readFileSync } from "node:fs";
import { TileMachine } from "../web/js/tileState.js";

const vectors = JSON.parse(readFileSync(new URL("./vectors/tile_states.json", import.meta.url)));
let failures = 0;

for (const scenario of vectors.scenarios) {
  const machine = new TileMachine(vectors.thresholds, scenario.steps[0].t);
  for (const step of scenario.steps) {
    if (step.frame) machine.onFrame(step.t);
    const actual = machine.update(step.t, {
      sourceState: step.source ?? "connecting",
      isStatic: step.static ?? false,
      black: step.black ?? false,
      paused: step.paused ?? false,
      offline: step.offline ?? false,
    });
    if (actual !== step.expect) {
      failures += 1;
      console.error(`${scenario.name} @${step.t}: expected ${step.expect}, got ${actual}`);
    }
  }
}
process.exit(failures ? 1 : 0);
