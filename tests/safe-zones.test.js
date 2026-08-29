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

test("scales the manual margin range to half of the source frame height", () => {
  const marginRangeMax = requireApi("marginRangeMax");

  assert.equal(marginRangeMax(1920), 960);
  assert.equal(marginRangeMax(3840), 1920);
  assert.equal(marginRangeMax(0), 960);
});

test("snaps a bottom caption fully inside the TikTok guide including visual bleed", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const safeMarginFor = requireApi("safeMarginFor");
  const state = setEnabled(createState(), "tiktok", true);

  assert.equal(safeMarginFor(state, "bottom", 1920, {
    highlight_style: "box",
    box_padding_y: 10,
    stroke_width: 0,
    shadow_enabled: true,
    shadow_blur: 6,
    shadow_offset: [0, 3],
  }), 412);
});

test("uses the strictest active guide when several zones overlap", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const safeMarginFor = requireApi("safeMarginFor");
  let state = createState();
  state = setEnabled(state, "tiktok", true);
  state = setEnabled(state, "reels", true);
  state = setEnabled(state, "shorts", true);

  assert.equal(safeMarginFor(state, "bottom", 1920, {
    highlight_style: "box",
    box_padding_y: 10,
    stroke_width: 0,
    shadow_enabled: true,
    shadow_blur: 6,
    shadow_offset: [0, 3],
  }), 451);
});

test("stores the strictest active edge as a normalized render rule", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const strictestInsetRatio = requireApi("strictestInsetRatio");
  let state = createState();
  state = setEnabled(state, "tiktok", true);
  state = setEnabled(state, "reels", true);

  assert.equal(strictestInsetRatio(state, "bottom"), 0.22);
  assert.equal(strictestInsetRatio(state, "top"), 0.10);
});

test("resolves one safe style independently for every frame height", () => {
  const effectiveMargin = requireApi("effectiveMargin");
  const style = {
    position: "bottom",
    position_margin: 190,
    position_mode: "safe",
    position_safe_inset_ratio: 0.22,
    highlight_style: "none",
    stroke_width: 0,
    shadow_enabled: false,
  };

  assert.equal(effectiveMargin(style, 1920), 423);
  assert.equal(effectiveMargin(style, 3840), 845);
});

test("falls back to manual pixels for invalid safe positioning data", () => {
  const effectiveMargin = requireApi("effectiveMargin");

  assert.equal(effectiveMargin({
    position: "bottom",
    position_margin: 317,
    position_mode: "safe",
    position_safe_inset_ratio: 0.75,
  }, 3840), 317);
  assert.equal(effectiveMargin({ position: "center", position_margin: 91 }, 1920), 91);
});

test("normalizes numeric preset strings but rejects boolean inset values", () => {
  const effectiveMargin = requireApi("effectiveMargin");
  const isSafePosition = requireApi("isSafePosition");
  const base = {
    position: "bottom",
    position_margin: 190,
    position_mode: "safe",
    highlight_style: "none",
    stroke_width: 0,
    shadow_enabled: false,
  };

  const imported = { ...base, position_safe_inset_ratio: "0.22" };
  assert.equal(effectiveMargin(imported, 1920), 423);
  assert.equal(isSafePosition(imported), true);
  assert.equal(isSafePosition({ ...base, position_safe_inset_ratio: false }), false);
  assert.equal(effectiveMargin({ ...base, position_safe_inset_ratio: false }, 1920), 190);
  assert.equal(effectiveMargin({ ...base, position_safe_inset_ratio: true }, 1920), 190);
  assert.equal(effectiveMargin({ ...base, position_safe_inset_ratio: [] }, 1920), 190);
  assert.equal(effectiveMargin({ ...base, position_safe_inset_ratio: [0.22] }, 1920), 190);
});

test("keeps fractional visual overflow in parity with the renderer", () => {
  const effectiveMargin = requireApi("effectiveMargin");

  assert.equal(effectiveMargin({
    position: "bottom",
    position_margin: 190,
    position_mode: "safe",
    position_safe_inset_ratio: 0.22,
    highlight_style: "box",
    box_padding_y: 10.2,
    stroke_width: 0,
    shadow_enabled: false,
  }, 1920), 433);
});

test("accounts for the renderer blur footprint and directional shadow offset", () => {
  const visualOverflow = requireApi("visualOverflow");
  const style = {
    highlight_style: "box",
    box_padding_y: 10,
    stroke_width: 2,
    shadow_enabled: true,
    shadow_blur: 20,
    shadow_offset: [0, 4],
  };

  assert.equal(visualOverflow(style, "bottom"), 64);
  assert.equal(visualOverflow(style, "top"), 60);
});

test("activates a normalized safe rule while keeping compatibility pixels", () => {
  const activateSafePosition = requireApi("activateSafePosition");
  const original = {
    position: "bottom",
    position_margin: 190,
    highlight_style: "none",
    stroke_width: 0,
    shadow_enabled: false,
  };

  const activated = activateSafePosition(original, 0.22, 1920);

  assert.equal(activated.position_mode, "safe");
  assert.equal(activated.position_safe_inset_ratio, 0.22);
  assert.equal(activated.position_margin, 423);
  assert.equal(original.position_mode, undefined);
});

test("manual input clears the safe rule and preserves exact slider pixels", () => {
  const activateManualPosition = requireApi("activateManualPosition");
  const style = {
    position: "bottom",
    position_margin: 451,
    position_mode: "safe",
    position_safe_inset_ratio: 0.22,
  };

  const manual = activateManualPosition(style, 777);

  assert.equal(manual.position_mode, "manual");
  assert.equal(manual.position_safe_inset_ratio, null);
  assert.equal(manual.position_margin, 777);
});

test("changing preview resolution recalculates pixels without changing the saved inset", () => {
  const activateSafePosition = requireApi("activateSafePosition");
  const effectiveMargin = requireApi("effectiveMargin");
  const style = activateSafePosition({
    position: "bottom",
    position_margin: 190,
    highlight_style: "none",
    stroke_width: 0,
    shadow_enabled: false,
  }, 0.22, 1920);

  assert.equal(effectiveMargin(style, 3840), 845);
  assert.equal(style.position_safe_inset_ratio, 0.22);
});

test("does not offer vertical snapping without a guide or at center position", () => {
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const safeMarginFor = requireApi("safeMarginFor");
  const state = setEnabled(createState(), "tiktok", true);

  assert.equal(safeMarginFor(createState(), "bottom", 1920, {}), null);
  assert.equal(safeMarginFor(state, "center", 1920, {}), null);
});

test("enables snapping only for an active guide on a vertical video", () => {
  const canSnapMargin = requireApi("canSnapMargin");
  const createState = requireApi("createState");
  const setEnabled = requireApi("setEnabled");
  const active = setEnabled(createState(), "tiktok", true);

  assert.equal(canSnapMargin(active, "bottom", 1080, 1920), true);
  assert.equal(canSnapMargin(active, "center", 1080, 1920), false);
  assert.equal(canSnapMargin(active, "bottom", 1920, 1080), false);
  assert.equal(canSnapMargin(createState(), "bottom", 1080, 1920), false);
});
