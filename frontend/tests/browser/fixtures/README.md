# FolderView SVG regression fixtures

These are the exact, unmodified SVG assets supplied for the clipping report:

- `shield.svg`: https://raw.githubusercontent.com/hernandito/unRAID-Docker-Folder-Animated-Icons---Alternate-Colors/master/Pale-Collection/pale-privacy.svg
  SHA-256: `f2d76706ecce16bd6f8bc33f710dae8b63b8fbb36a2fa3eb8588d415e2f6cc0e`
- `ai.svg`: https://raw.githubusercontent.com/hernandito/unRAID-Docker-Folder-Animated-Icons---Alternate-Colors/master/Pale-Collection/pale-ai3.svg
  SHA-256: `abd5a227d4b9f361b1cdb71c15de18ad6c372053c42c72e214e2db2d41a0efff`

Artwork/source: hernandito, unRAID Docker Folder Animated Icons — Alternate Colors,
Pale Collection. Keep these original bytes intact. Tests intercept their original
URLs and serve these files offline; only the test responses pause CSS animations
for deterministic screenshot comparison. Production image preparation preserves
animation, artwork, viewBox and internal clipping paths.

Both SVGs have a 650 × 650 viewBox with no width/height attributes. Chromium can
crop this form when Cytoscape supplies its inferred intrinsic dimensions as the
source rectangle of nine-argument drawImage. Preparing explicit dimensions on the
isolated SVG image resource fixes the source crop; disabling the node clipping
mask alone does not. The card still uses background-fit:none, 24 × 24 images,
centred horizontally at 10px from its top, and a label starting at 42px. Its
220 × 92 footprint, group identities and interaction/layout code are unchanged.

Chromium tests compare actual card screenshots at 75%, 100% and 200% zoom in both
themes, plus independently compare complete SVG pixels with the rendered output.
The screenshot baselines were visually inspected. A negative-control run using
the original dimensionless SVGs fails those baselines. The existing tests also
cover expansion, collapse, persisted manual anchors, connections and Graph mode.

Run from frontend/: `CHROMIUM_PATH=/usr/bin/chromium npm run test:browser`.
For Playwright's bundled Chromium, omit CHROMIUM_PATH. Baselines are Linux images;
use a consistent browser/platform when updating them and inspect every update.
