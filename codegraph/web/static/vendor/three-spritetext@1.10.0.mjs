/**
 * three-spritetext@1.10.0 — offline/vendored stub
 *
 * three-spritetext requires the same THREE.js instance used by 3d-force-graph.
 * 3d-force-graph@1 bundles THREE internally and does not expose it as window.THREE.
 * Downloading a separate three.js UMD (~600 KB, r128) introduces version skew
 * that breaks WebGL object compatibility.
 *
 * Result: SpriteText is intentionally left undefined.  The calling code in
 * index.html already wraps the import in a try/catch and falls back to HTML
 * hover-labels when window.SpriteText is absent (see graph3d.js:makeLabelSprite).
 * The 3D graph works fully — only the always-visible 3D text labels are absent.
 *
 * To restore sprite labels: load an external three.js UMD that matches
 * 3d-force-graph's bundled version before loading 3d-force-graph@1.min.js,
 * then window.THREE will be set and three-spritetext UMD will work.
 */
export default undefined;
export const SpriteText = undefined;
