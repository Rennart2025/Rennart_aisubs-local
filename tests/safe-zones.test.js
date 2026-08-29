const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const modulePath = path.join(__dirname, "..", "gui", "safe-zones.js");
const safeZones = fs.existsSync(modulePath) ? require(modulePath) : {};

function requireApi(name) {
  assert.equal(typeof safeZones[name], "function", `${name} must be exported`);
  return safeZones[name];
}

test("starts every preview session with all platform guides disabled", () => {
  const createState = requireApi("createState");

  assert.deepEqual(createState(), {
    tiktok: false,
    reels: false,
    shorts: false,
  });
});

test("keeps platform guides independent when several are enabled", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const activePlatforms = requireApi("activePlatforms");

  let state = createState();
  state = setEnabled(state, "tiktok", true);
  state = setEnabled(state, "shorts", true);

  assert.deepEqual(activePlatforms(state), ["tiktok", "shorts"]);
  assert.equal(state.reels, false);
});

test("turning one guide off does not change the other active guides", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const activePlatforms = requireApi("activePlatforms");

  let state = createState();
  state = setEnabled(state, "tiktok", true);
  state = setEnabled(state, "reels", true);
  state = setEnabled(state, "shorts", true);
  state = setEnabled(state, "reels", false);

  assert.deepEqual(activePlatforms(state), ["tiktok", "shorts"]);
});

test("does not accept an unknown social platform", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");

  assert.throws(
    () => setEnabled(createState(), "unknown", true),
    /Unknown safe-zone platform/,
  );
});

test("recognizes the vertical 9:16 format used by the guides", () => {
  const isVerticalFormat = requireApi("isVerticalFormat");

  assert.equal(isVerticalFormat(1080, 1920), true);
  assert.equal(isVerticalFormat(720, 1280), true);
  assert.equal(isVerticalFormat(1080, 1918), true);
  assert.equal(isVerticalFormat(1080, 1823), false);
  assert.equal(isVerticalFormat(1920, 1080), false);
  assert.equal(isVerticalFormat(1080, 1080), false);
  assert.equal(isVerticalFormat(0, 1920), false);
});

test("exposes the format warning as a polite status message", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "gui", "index.html"), "utf8");

  assert.match(
    html,
    /id="safeZoneFormatHint"[^>]*role="status"[^>]*aria-live="polite"/,
  );
});

test("returns one normalized overlay definition for every active platform", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const overlayDefinitions = requireApi("overlayDefinitions");

  let state = createState();
  state = setEnabled(state, "tiktok", true);
  state = setEnabled(state, "reels", true);
  state = setEnabled(state, "shorts", true);

  const definitions = overlayDefinitions(state);
  assert.deepEqual(definitions.map((item) => item.id), ["tiktok", "reels", "shorts"]);
  assert.deepEqual(definitions.map((item) => item.label), ["TikTok", "Reels", "Shorts"]);
  for (const item of definitions) {
    for (const edge of ["top", "right", "bottom", "left"]) {
      assert.ok(item.inset[edge] >= 0 && item.inset[edge] < 50, `${item.id}.${edge}`);
    }
  }
});

test("returns no overlay definitions while all switches are off", () => {
  const createState = requireApi("createState");
  const overlayDefinitions = requireApi("overlayDefinitions");

  assert.deepEqual(overlayDefinitions(createState()), []);
});
