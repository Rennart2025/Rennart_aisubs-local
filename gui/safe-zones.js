(function (root, factory) {
  const value = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = value;
  if (root) root.SafeZones = value;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const PLATFORM_ORDER = ["tiktok", "reels", "shorts"];
  const PLATFORM_GUIDES = {
    tiktok: {
      id: "tiktok",
      label: "TikTok",
      inset: { top: 10, right: 21, bottom: 20, left: 7 },
    },
    reels: {
      id: "reels",
      label: "Reels",
      inset: { top: 8, right: 16, bottom: 22, left: 6 },
    },
    shorts: {
      id: "shorts",
      label: "Shorts",
      inset: { top: 10, right: 18, bottom: 18, left: 6 },
    },
  };

  function createState() {
    return { tiktok: false, reels: false, shorts: false };
  }

  function setEnabled(state, platform, enabled) {
    if (!PLATFORM_ORDER.includes(platform)) {
      throw new Error(`Unknown safe-zone platform: ${platform}`);
    }
    return Object.assign({}, state, { [platform]: Boolean(enabled) });
  }

  function activePlatforms(state) {
    return PLATFORM_ORDER.filter((platform) => Boolean(state && state[platform]));
  }

  function overlayDefinitions(state) {
    return activePlatforms(state).map((platform) => {
      const guide = PLATFORM_GUIDES[platform];
      return {
        id: guide.id,
        label: guide.label,
        inset: Object.assign({}, guide.inset),
      };
    });
  }

  function isVerticalFormat(width, height) {
    if (!(width > 0 && height > 0)) return false;
    const targetRatio = 9 / 16;
    const relativeError = Math.abs(width / height - targetRatio) / targetRatio;
    return relativeError <= 0.005;
  }

  function marginRangeMax(videoHeight, requiredMargin) {
    const sourceHeight = videoHeight > 0 ? videoHeight : 1920;
    return Math.max(400, Math.ceil(sourceHeight / 2), Math.ceil(requiredMargin || 0));
  }

  function validInsetRatio(value) {
    if (typeof value !== "number" && typeof value !== "string") return null;
    if (typeof value === "string" && !value.trim()) return null;
    const ratio = Number(value);
    return Number.isFinite(ratio) && ratio >= 0 && ratio <= 0.5 ? ratio : null;
  }

  function isSafePosition(style) {
    const value = style || {};
    return value.position_mode === "safe"
      && (value.position === "top" || value.position === "bottom")
      && validInsetRatio(value.position_safe_inset_ratio) !== null;
  }

  function strictestInsetRatio(state, position) {
    if (position !== "top" && position !== "bottom") return null;
    const guides = overlayDefinitions(state);
    if (!guides.length) return null;
    return Math.max(...guides.map((guide) => guide.inset[position])) / 100;
  }

  function visualOverflow(style, position) {
    const value = style || {};
    const boxBleed = value.highlight_style === "box" ? Math.max(0, Number(value.box_padding_y) || 0) : 0;
    const strokeBleed = Math.max(0, Number(value.stroke_width) || 0);
    let shadowBleed = 0;
    if (value.shadow_enabled) {
      const offsetY = Array.isArray(value.shadow_offset) ? Number(value.shadow_offset[1]) || 0 : 0;
      const directionalOffset = position === "top" ? Math.max(0, -offsetY) : Math.max(0, offsetY);
      const blurFootprint = Math.ceil(2.5 * Math.max(0, Number(value.shadow_blur) || 0));
      shadowBleed = blurFootprint + directionalOffset;
    }
    return Math.max(boxBleed, strokeBleed) + shadowBleed;
  }

  function effectiveMargin(style, videoHeight) {
    const value = style || {};
    const manualValue = Number(value.position_margin);
    const manual = Number.isFinite(manualValue) ? Math.max(0, manualValue) : 0;
    const insetRatio = validInsetRatio(value.position_safe_inset_ratio);
    if (!isSafePosition(value) || insetRatio === null || !(videoHeight > 0)) {
      return manual;
    }
    return Math.max(0, Math.ceil(videoHeight * insetRatio + visualOverflow(value, value.position)));
  }

  function activateSafePosition(style, insetRatio, videoHeight) {
    const validRatio = validInsetRatio(insetRatio);
    if (validRatio === null) return activateManualPosition(style, style && style.position_margin);
    const next = Object.assign({}, style, {
      position_mode: "safe",
      position_safe_inset_ratio: validRatio,
    });
    next.position_margin = effectiveMargin(next, videoHeight);
    return next;
  }

  function activateManualPosition(style, margin) {
    const number = Number(margin);
    return Object.assign({}, style, {
      position_mode: "manual",
      position_safe_inset_ratio: null,
      position_margin: Number.isFinite(number) ? Math.max(0, number) : 0,
    });
  }

  function safeMarginFor(state, position, videoHeight, style) {
    if (!(videoHeight > 0) || (position !== "top" && position !== "bottom")) return null;
    const insetRatio = strictestInsetRatio(state, position);
    if (insetRatio === null) return null;
    return Math.ceil(videoHeight * insetRatio + visualOverflow(style, position));
  }

  function canSnapMargin(state, position, videoWidth, videoHeight) {
    return activePlatforms(state).length > 0
      && (position === "top" || position === "bottom")
      && isVerticalFormat(videoWidth, videoHeight);
  }

  return {
    activateManualPosition,
    activateSafePosition,
    activePlatforms,
    canSnapMargin,
    createState,
    effectiveMargin,
    isSafePosition,
    isVerticalFormat,
    marginRangeMax,
    overlayDefinitions,
    safeMarginFor,
    setEnabled,
    strictestInsetRatio,
    visualOverflow,
  };
});
