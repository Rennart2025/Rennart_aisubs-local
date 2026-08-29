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

  return { activePlatforms, createState, isVerticalFormat, overlayDefinitions, setEnabled };
});
