# Vendored Frontend Dependencies

All files in this directory are vendored copies of third-party libraries.
The dashboard serves them locally so it works fully offline.

## Manifest

| File | Library | Version | Source URL | Size |
|------|---------|---------|-----------|------|
| `d3.v7.min.js` | D3.js | 7.9.0 | https://d3js.org/d3.v7.min.js | 273 KB |
| `d3-sankey@0.12.3.min.js` | d3-sankey | 0.12.3 | https://cdn.jsdelivr.net/npm/d3-sankey@0.12.3/dist/d3-sankey.min.js | 6 KB |
| `mermaid@10.9.1.min.js` | Mermaid | 10.9.1 | https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js | 3.2 MB |
| `lucide@0.414.0.min.js` | Lucide Icons | 0.414.0 | https://unpkg.com/lucide@0.414.0 | 336 KB |
| `3d-force-graph@1.min.js` | 3d-force-graph | 1.80.0 | https://unpkg.com/3d-force-graph@1/dist/3d-force-graph.min.js | 1.3 MB |
| `three-spritetext@1.10.0.mjs` | three-spritetext | 1.10.0 | https://esm.sh/three-spritetext@1.10.0 | stub (see below) |
| `fonts.css` | Font declarations | — | local | 1 KB |
| `fonts/InterVariable.woff2` | Inter (variable) | 4.1 | https://rsms.me/inter/font-files/InterVariable.woff2 | 344 KB |
| `fonts/JetBrainsMono-400-latin.woff2` | JetBrains Mono | v24 | https://fonts.gstatic.com (latin subset, wt 400–500) | 31 KB |

**Total vendored size**: ~5.3 MB

## Notes

### three-spritetext stub
`three-spritetext@1.10.0.mjs` is a no-op stub. `three-spritetext` requires the
same `THREE.js` instance used by `3d-force-graph`. The `3d-force-graph@1` UMD bundle
embeds THREE internally and does not expose `window.THREE`, making it impossible to
share a compatible THREE instance without also vendoring a full three.js UMD (~600 KB,
version r128 or older). This would push total vendored size over the 6 MB budget and
introduce version-skew fragility.

The calling code in `index.html` already wraps the import in `try/catch` and falls
back to HTML hover-labels when `window.SpriteText` is absent. The 3D graph works
fully in offline mode; only the always-visible 3D text labels on nodes/edges are
absent. HTML hover-labels remain fully functional.

### Tailwind CSS
The Tailwind CDN runtime is NOT vendored (would add ~300 KB and requires a JS
runtime to generate CSS). Instead, `app.css` has been extended with a lightweight
utility layer (`/* --- Tailwind-compat utilities --- */`) that covers the small set
of utility classes used in `index.html`. Custom design tokens (`ink-*`, `brand-*`,
`accent-*`, `shadow-card`, `shadow-glow`) are expressed as CSS variables already
defined in `app.css`.

## Re-vendoring (update instructions)

To update a library, download its latest minified bundle to this directory using
the source URL above and update the version in this manifest. For `mermaid`, use the
`dist/mermaid.min.js` file from jsdelivr (not `mermaid.esm.min.mjs`).
