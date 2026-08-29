# Safe-Zone Caption Positioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `По зоне` a per-video safe-positioning rule that stays correct in mixed-resolution Auto and Manual batches while preserving manual margins and old presets.

**Architecture:** The browser stores a validated normalized safe inset in the style payload and shows the effective pixel value for the current preview. The Python renderer resolves that inset against each decoded video canvas and adds the same conservative visual-overflow rule, while the media probe reports rotation-correct display dimensions to the browser.

**Tech Stack:** Vanilla JavaScript/CommonJS tests with Node's built-in test runner, Python 3 `unittest`, Pillow, MoviePy, ffprobe, pywebview HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-08-29-safe-zone-positioning-design.md`

## Global Constraints

- TikTok, Reels, and Shorts guides are preview-only, independently stackable, and disabled at every application start.
- `position_margin` remains the backward-compatible manual margin.
- Safe mode is optional and represented by `position_mode: "safe"` plus `position_safe_inset_ratio` in the inclusive range `0.0..0.5`.
- Auto and Manual modes must submit the same style contract; effective safe pixels are resolved separately for every rendered file.
- Moving the margin slider or changing top/center/bottom position returns to manual mode.
- No new runtime dependency is allowed.
- Existing cancellation, retry, partial-failure, transcript, output, and preset behavior must remain intact.

---

### Task 1: Pure browser safe-positioning contract

**Files:**
- Modify: `gui/safe-zones.js`
- Modify: `tests/safe-zones.test.js`

**Interfaces:**
- Consumes: platform guide definitions and a style object with `position`, `position_margin`, optional `position_mode`, and optional `position_safe_inset_ratio`.
- Produces: `strictestInsetRatio(state, position) -> number|null`, `visualOverflow(style, position) -> number`, and `effectiveMargin(style, videoHeight) -> number`.

- [ ] **Step 1: Add failing tests for strictest inset and mixed-resolution margins**

```js
test("stores the strictest active edge as a normalized render rule", () => {
  let state = SafeZones.createState();
  state = SafeZones.setEnabled(state, "tiktok", true);
  state = SafeZones.setEnabled(state, "reels", true);
  assert.equal(SafeZones.strictestInsetRatio(state, "bottom"), 0.22);
  assert.equal(SafeZones.strictestInsetRatio(state, "top"), 0.10);
});

test("resolves one safe style independently for every frame height", () => {
  const style = {
    position: "bottom", position_margin: 190,
    position_mode: "safe", position_safe_inset_ratio: 0.22,
    highlight_style: "none", stroke_width: 0, shadow_enabled: false,
  };
  assert.equal(SafeZones.effectiveMargin(style, 1920), 423);
  assert.equal(SafeZones.effectiveMargin(style, 3840), 845);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/safe-zones.test.js`

Expected: FAIL because `strictestInsetRatio` and `effectiveMargin` are not exported.

- [ ] **Step 3: Implement validation, visual overflow, safe activation, and manual fallback**

```js
function validInsetRatio(value) {
  const ratio = Number(value);
  return Number.isFinite(ratio) && ratio >= 0 && ratio <= 0.5 ? ratio : null;
}

function strictestInsetRatio(state, position) {
  if (position !== "top" && position !== "bottom") return null;
  const guides = overlayDefinitions(state);
  return guides.length
    ? Math.max(...guides.map((guide) => guide.inset[position])) / 100
    : null;
}

function visualOverflow(style, position) {
  const pill = style.highlight_style === "box" ? Math.max(0, Number(style.box_padding_y) || 0) : 0;
  const stroke = Math.max(0, Number(style.stroke_width) || 0);
  if (!style.shadow_enabled) return Math.max(pill, stroke);
  const blur = Math.ceil(2.5 * Math.max(0, Number(style.shadow_blur) || 0));
  const offsetY = Array.isArray(style.shadow_offset) ? Number(style.shadow_offset[1]) || 0 : 0;
  const offset = position === "top" ? Math.max(0, -offsetY) : Math.max(0, offsetY);
  return Math.max(pill, stroke) + blur + offset;
}
```

`effectiveMargin` must use safe mode only for top/bottom with valid height and inset; otherwise it returns a nonnegative numeric `position_margin`.

- [ ] **Step 4: Run the focused JavaScript tests and verify GREEN**

Run: `node --test tests/safe-zones.test.js`

Expected: all safe-zone tests PASS, including invalid inset, center position, maximum blur, and manual activation cases.

- [ ] **Step 5: Commit the pure contract**

```powershell
git add -- gui/safe-zones.js tests/safe-zones.test.js
git commit -m "feat: define safe positioning contract"
```

---

### Task 2: Authoritative per-file renderer margin

**Files:**
- Modify: `renderer.py`
- Create: `tests/test_safe_positioning.py`

**Interfaces:**
- Consumes: the style fields defined in Task 1 and the actual decoded `video_h`.
- Produces: `_visual_overflow(style, position) -> int` and `_effective_position_margin(style, video_h) -> int`, used by `_render_state_image` before block placement.

- [ ] **Step 1: Add failing unit tests for compatibility and per-file resolution**

```python
class EffectivePositionMarginTests(unittest.TestCase):
    def test_resolves_same_safe_rule_for_each_video_height(self):
        style = dict(renderer.DEFAULT_STYLE)
        style.update(position="bottom", position_mode="safe",
                     position_safe_inset_ratio=0.22,
                     highlight_style="none", stroke_width=0,
                     shadow_enabled=False)
        self.assertEqual(renderer._effective_position_margin(style, 1920), 423)
        self.assertEqual(renderer._effective_position_margin(style, 3840), 845)

    def test_legacy_and_invalid_safe_styles_use_manual_pixels(self):
        legacy = dict(renderer.DEFAULT_STYLE, position_margin=317)
        invalid = dict(legacy, position_mode="safe", position_safe_inset_ratio=0.75)
        self.assertEqual(renderer._effective_position_margin(legacy, 3840), 317)
        self.assertEqual(renderer._effective_position_margin(invalid, 3840), 317)
```

- [ ] **Step 2: Run the focused Python tests and verify RED**

Run: `.\python\python.exe -m unittest tests.test_safe_positioning -v`

Expected: FAIL because `_effective_position_margin` does not exist.

- [ ] **Step 3: Implement the renderer helpers and use the effective value in layout**

```python
def _valid_safe_inset(value):
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    return ratio if 0.0 <= ratio <= 0.5 else None

def _effective_position_margin(style, video_h):
    manual = max(0, int(float(style.get("position_margin", 0) or 0)))
    ratio = _valid_safe_inset(style.get("position_safe_inset_ratio"))
    if (style.get("position_mode") != "safe" or ratio is None
            or style.get("position") not in {"top", "bottom"} or video_h <= 0):
        return manual
    return max(0, math.ceil(video_h * ratio + _visual_overflow(style, style["position"])))
```

Inside `_render_state_image`, calculate `position_margin = _effective_position_margin(style, video_h)` once and use it for top/bottom block placement. `_visual_overflow` must mirror Task 1, including `ceil(2.5 * blur)` and directional offset.

- [ ] **Step 4: Add renderer-backed alpha-bound regression tests**

Use the bundled Montserrat font, a 1080x1920 transparent state image, `shadow_blur=20`, and both top and bottom positions. Assert the alpha channel bounding box begins at or below the top safe boundary and ends at or above neither the bottom safe boundary:

```python
self.assertGreaterEqual(alpha_bbox[1], math.floor(1920 * 0.10))
self.assertLessEqual(alpha_bbox[3], math.ceil(1920 * (1 - 0.22)))
```

The expected bounds are literal safe-zone geometry, not values calculated with renderer helpers.

- [ ] **Step 5: Run renderer tests and the complete Python suite**

Run: `.\python\python.exe -m unittest tests.test_safe_positioning -v`

Run: `.\python\python.exe -m unittest discover -s tests -v`

Expected: focused renderer tests and all Python tests PASS.

- [ ] **Step 6: Commit per-file rendering**

```powershell
git add -- renderer.py tests/test_safe_positioning.py
git commit -m "feat: resolve safe margin per rendered video"
```

---

### Task 3: Rotation-correct preview dimensions

**Files:**
- Modify: `mediaserver.py`
- Create: `tests/test_media_orientation.py`

**Interfaces:**
- Consumes: raw ffprobe stream width, height, `tags.rotate`, and `side_data_list[].rotation`.
- Produces: `_display_dimensions(width, height, rotation) -> tuple[int, int]` and `_stream_rotation(stream) -> float|None`; `probe()` returns display-oriented `width` and `height`.

- [ ] **Step 1: Add failing orientation tests**

```python
class DisplayDimensionsTests(unittest.TestCase):
    def test_quarter_turns_swap_dimensions(self):
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, 90), (1080, 1920))
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, -90), (1080, 1920))
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, 270), (1080, 1920))

    def test_half_turn_and_bad_metadata_keep_dimensions(self):
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, 180), (1920, 1080))
        self.assertEqual(mediaserver._display_dimensions(1920, 1080, "bad"), (1920, 1080))

    def test_side_data_rotation_takes_precedence_over_legacy_tag(self):
        stream = {"tags": {"rotate": "0"}, "side_data_list": [{"rotation": -90}]}
        self.assertEqual(mediaserver._stream_rotation(stream), -90.0)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.\python\python.exe -m unittest tests.test_media_orientation -v`

Expected: FAIL because both orientation helpers are missing.

- [ ] **Step 3: Implement metadata parsing and request it from ffprobe**

Use this ffprobe entry selection:

```python
"stream=width,height,r_frame_rate:stream_tags=rotate:stream_side_data=rotation"
```

`_stream_rotation` checks side data first, then the legacy tag. `_display_dimensions` converts a numeric rotation modulo 360 and swaps only when it is within 0.5 degrees of 90 or 270. `probe()` applies the helper before caching and returning dimensions.

- [ ] **Step 4: Run orientation and complete Python tests**

Run: `.\python\python.exe -m unittest tests.test_media_orientation -v`

Run: `.\python\python.exe -m unittest discover -s tests -v`

Expected: all tests PASS and malformed metadata falls back without raising.

- [ ] **Step 5: Commit rotation handling**

```powershell
git add -- mediaserver.py tests/test_media_orientation.py
git commit -m "fix: honor video display rotation in preview"
```

---

### Task 4: Safe/manual UI state and preset behavior

**Files:**
- Modify: `gui/app.js`
- Modify: `gui/index.html`
- Modify: `tests/safe-zones.test.js`

**Interfaces:**
- Consumes: Task 1 pure helpers and `previewVideo.width/height` from the rotation-correct probe.
- Produces: `activateSafePosition(style, insetRatio, videoHeight) -> object`, `activateManualPosition(style, margin) -> object`, a style payload shared unchanged by `runPipeline()` and `startManualRender()`, an accessible `По зоне` selected state, and dynamic preview pixels.

- [ ] **Step 1: Extend failing state tests before changing event handlers**

Add literal assertions that the not-yet-existing `activateSafePosition` stores ratio and compatibility pixels and `activateManualPosition` clears safe state. Also assert that changing preview height changes `effectiveMargin` without changing the ratio. The production regression each test catches is respectively: saving only pixels, leaving safe mode active after manual input, and making batch behavior preview-dependent.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/safe-zones.test.js`

Expected: FAIL because `activateSafePosition` and `activateManualPosition` are not exported.

- [ ] **Step 3: Wire safe activation and manual escape in `gui/app.js`**

Set default fields:

```js
position_mode: "manual",
position_safe_inset_ratio: null,
```

Implement both pure transition helpers in `gui/safe-zones.js`: `activateSafePosition` validates the ratio, copies the style, sets safe mode, and stores current effective pixels as compatibility fallback; `activateManualPosition` copies the style, sets manual mode, clears the ratio, and stores a nonnegative margin. On `По зоне`, get `strictestInsetRatio(safeZoneState, style.position)` and replace `style` with `activateSafePosition(style, ratio, previewVideo.height)`. On slider input, replace `style` with `activateManualPosition(style, rawValue)`. On position toggle, switch to manual before storing the new position. Every preview draw and control hydration displays `SafeZones.effectiveMargin(style, previewVideo.height)` while keeping the normalized ratio unchanged.

- [ ] **Step 4: Complete button and status semantics in `gui/index.html` and `renderSafeZones()`**

The button keeps its compact placement next to `Отступ от края`, uses `aria-pressed="true"` only when safe mode is active for top/bottom, and exposes disabled/focus/hover/active states. Hints cover no-video, wrong-format, no-guide, center, ready, active-safe, and safe-preset-with-guides-hidden states. Guide toggles remain independent and do not persist.

- [ ] **Step 5: Verify JavaScript syntax and all Node tests**

Run: `node --check gui/safe-zones.js`

Run: `node --check gui/app.js`

Run: `node --test tests/*.test.js`

Expected: syntax checks exit 0 and all Node tests PASS.

- [ ] **Step 6: Commit UI integration**

```powershell
git add -- gui/app.js gui/index.html tests/safe-zones.test.js
git commit -m "feat: add safe and manual caption positioning"
```

---

### Task 5: End-to-end batch and browser verification

**Files:**
- Modify only if verification exposes a tested defect: files from Tasks 1-4 and the matching test file.

**Interfaces:**
- Consumes: complete safe-positioning contract.
- Produces: verification evidence that Auto, Manual, presets, mixed resolutions, rotation, and accessibility satisfy the spec.

- [ ] **Step 1: Run the complete automated suite and static checks**

Run: `node --test tests/*.test.js`

Run: `.\python\python.exe -m unittest discover -s tests -v`

Run: `node --check gui/safe-zones.js`

Run: `node --check gui/app.js`

Run: `git diff --check`

Expected: every command exits 0 with no failing test or syntax error.

- [ ] **Step 2: Exercise the running application in the local browser**

Verify these observable outcomes:

1. Fresh load: all three guides off, button disabled, keyboard focus visible.
2. 1080x1920 preview + TikTok: button enabled; click selects safe mode and reports effective pixels.
3. Add Reels and Shorts: overlays stack and strictest bottom edge becomes Reels 22%.
4. Switch preview to 2160x3840: reported pixels update to the larger frame while the safe ratio remains 0.22.
5. Move the slider: `aria-pressed` becomes false and exact manual pixels appear.
6. Load a safe preset with guides hidden: safe preview remains active and hint suggests enabling a guide.
7. Center position or non-9:16 preview: snapping is unavailable with an explanatory hint.

- [ ] **Step 3: Prove Auto and Manual share the contract**

Run one two-file Auto batch and one Manual render using the same safe preset. Inspect both outputs or renderer-backed frames and confirm each file's visible alpha stays inside its selected boundary. Confirm cancellation, retry, and file-level failure controls are unchanged and still available in their prior states.

- [ ] **Step 4: Re-read the spec acceptance criteria against evidence**

Record the automated test names or browser observation that proves each of the eight acceptance criteria. If any criterion lacks evidence, add a failing regression test before changing production code, then repeat the relevant checks.

- [ ] **Step 5: Inspect the final repository state**

Run: `git status --short`

Run: `git log -5 --oneline`

Expected: only intended safe-positioning files are changed or committed; no temporary preview harness, generated video, cache, or unrelated user file is staged.
