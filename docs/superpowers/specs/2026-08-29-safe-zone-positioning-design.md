# Safe-Zone Caption Positioning Design

## Goal

Let an editor place top- or bottom-aligned captions inside one or more social-platform safe zones with one action, while preserving predictable manual positioning and correct behavior for mixed-resolution Auto and Manual batches.

## Product contract

- TikTok, Reels, and Shorts guides remain preview-only controls and start disabled in every application session.
- Guides can be enabled independently and overlaid. When the user selects several guides, snapping uses the strictest active edge.
- `По зоне` is available only when a 9:16 preview is loaded, at least one guide is active, and caption position is `top` or `bottom`.
- Clicking `По зоне` activates safe positioning. It does not merely copy an absolute pixel value from the preview.
- The margin slider remains available. Moving it immediately returns the style to manual positioning.
- Auto mode, Manual mode, saved presets, and batch rendering use the same positioning contract.
- Existing presets and API callers that only provide `position_margin` retain their current behavior.

## Alternatives considered

### Selected: normalized safe edge resolved per rendered file

Store the selected safe edge as a ratio and resolve it against each render canvas. This keeps a TikTok/Reels/Shorts boundary correct for 1080x1920, 2160x3840, and other resolutions in the same queue. Visual overflow from the current caption style is added in render pixels.

### Rejected: copy preview pixels into `position_margin`

This is simple but makes batch output depend on which queued file happened to be previewed. A value suitable for 1920 px height is wrong at 3840 px height.

### Rejected: calculate from the largest queued video

This avoids unsafe output on the largest frame but pushes captions unnecessarily far from the edge on smaller videos and becomes order- and queue-dependent.

## Style data model

The style payload gains two optional fields:

```json
{
  "position_mode": "manual",
  "position_safe_inset_ratio": null
}
```

- `position_mode` is `manual` or `safe`. Missing and unknown values are treated as `manual`.
- `position_safe_inset_ratio` is the selected top or bottom guide inset expressed as a fraction of frame height, for example `0.22` for the Reels bottom edge.
- `position_margin` remains the manual margin and compatibility fallback. When safe mode is activated, the UI also writes the currently displayed effective pixel margin to this field so older consumers degrade to a usable result.
- Moving the margin slider sets `position_mode` to `manual` and clears `position_safe_inset_ratio`.
- Changing caption position does not reinterpret a top inset as a bottom inset or vice versa. It returns the style to manual mode; the user can then snap against the new edge.
- Presets save the two optional fields. Old presets load as manual. A safe preset remains safe even though preview guides start disabled; guides are not persisted.

## Margin calculation

Both preview and renderer use the same conceptual calculation:

```text
effective margin = ceil(frame height * selected inset ratio + visual overflow)
```

`visual overflow` includes:

- vertical pill padding when the highlight type is `box`;
- text stroke width;
- enabled shadow offset in the direction of the selected edge;
- a conservative Pillow Gaussian blur footprint of `ceil(2.5 * shadow_blur)`.

The calculation must never return a negative value. Invalid safe-mode data falls back to `position_margin` rather than failing a render. Center-aligned captions continue to ignore edge margin.

The renderer is authoritative: it resolves the effective margin from the actual `VideoFileClip` canvas height for every file. The browser preview calculates the same value for feedback, slider range, and the displayed pixel label.

## UI states and interaction

- No preview: button disabled; hint asks for a vertical video.
- Non-9:16 preview: button disabled; hint explains that the guides target 9:16.
- No active guide: button disabled; hint asks the user to enable TikTok, Reels, or Shorts.
- Center position: button disabled; hint explains that edge margin does not apply.
- Ready: button enabled; hint explains that the strictest active zone will be used.
- Safe mode active: button exposes a selected state and the hint reports the effective preview margin. Changing font, stroke, pill padding, shadow, or preview video recomputes the effective value automatically.
- Manual slider input: safe selected state disappears immediately and the displayed value is the chosen manual pixel margin.
- Preset-safe state without visible guides: the preview still uses the saved safe inset; the hint identifies safe positioning and suggests enabling a guide to inspect it.

The slider maximum is dynamic: at least 400 px, at least half of the preview frame height, and never lower than the current effective value. This preserves efficient manual positioning on high-resolution videos.

## Batch and mode behavior

Auto mode sends one style rule to the pipeline, but the renderer resolves the rule separately for each file. Manual mode passes the same style rule into its render phase and receives identical results. Queue order and the currently previewed item do not affect rendered placement.

Cancellation, retry, partial failure, transcription caching, and transcript approval are unchanged. Retrying or re-rendering a file recalculates its safe margin from that file's actual canvas.

## Rotation-aware preview geometry

Phone videos may store landscape pixel dimensions plus a 90- or 270-degree display rotation. The media probe must request rotation metadata from ffprobe and return display-oriented width and height to the UI. Rotation values are normalized modulo 360; 90 and 270 swap width and height, while 0 and 180 do not.

If rotation metadata is missing or malformed, the raw dimensions remain the fallback. The renderer continues to use the dimensions of its decoded canvas, avoiding a second independent orientation transform.

## Components and responsibilities

- `gui/safe-zones.js`: pure guide state, format eligibility, safe inset selection, visual-overflow calculation, effective preview margin, and dynamic range maximum.
- `gui/app.js`: UI state transitions, manual/safe mode switching, preset hydration, preview updates, and style payload construction.
- `gui/index.html`: compact `По зоне` control and accessible status/selected states.
- `renderer.py`: authoritative per-file effective-margin calculation before caption layout.
- `mediaserver.py`: rotation-aware display dimensions for preview eligibility and geometry.

No platform selection is added to the render API. The selected inset ratio is a complete render rule and keeps preview-only guide state out of presets and batch jobs.

## Compatibility and validation

- Missing `position_mode`: manual.
- Unknown `position_mode`: manual.
- Missing, nonnumeric, negative, or implausibly large safe inset: fall back to manual margin.
- Existing `position_margin` values are not migrated or rewritten on load.
- The safe inset is accepted in the inclusive range `0.0` to `0.5`; the current guides remain well within it.
- The feature introduces no new runtime dependency.

## Test strategy

### JavaScript unit tests

- strictest active top and bottom guide selection;
- effective margins at 1080x1920 and 2160x3840;
- visual overflow for pill, stroke, shadow direction, and maximum blur;
- invalid safe data falling back to manual;
- manual slider and position-change mode transitions through pure state helpers where possible;
- dynamic slider maximum and 9:16 eligibility.

### Python unit and renderer tests

- per-file margin resolution for two heights using one style payload;
- legacy and invalid payload fallback;
- top and bottom alpha bounds remain inside the selected safe boundary with maximum supported blur;
- rotation normalization for 0, 90, 180, 270, negative, and malformed metadata.

### Integration and browser checks

- guides start disabled;
- overlapping guides choose the strictest boundary;
- `По зоне` selected state and hints are understandable;
- changing preview between two resolutions changes the displayed pixel margin without changing the saved ratio;
- moving the slider returns to manual mode;
- Auto and Manual submit the same safe style contract;
- keyboard focus, disabled state, and status announcement remain accessible.

## Out of scope

- Platform-specific horizontal collision maps or animated social UI overlays.
- Automatically enabling or persisting guide toggles.
- Scaling font size and every caption-style dimension by output resolution.
- Changing transcription, queue cancellation, retry, output naming, or destructive-action behavior.

## Acceptance criteria

1. A style snapped to a Reels bottom edge renders inside that edge on both 1080x1920 and 2160x3840 files in one batch.
2. Batch result does not depend on which queue item is previewed or on queue order.
3. Maximum supported shadow blur does not produce nontransparent pixels outside the selected top or bottom safe boundary in renderer regression tests.
4. Moving `Отступ от края` restores exact manual-pixel behavior.
5. Old presets without new fields render exactly through the legacy manual path.
6. A portrait phone video represented as landscape dimensions plus 90-degree rotation is recognized as 9:16 in the preview.
7. Auto and Manual modes both pass the same safe rule and render it per file.
8. TikTok, Reels, and Shorts guides still start disabled and remain independently stackable.
