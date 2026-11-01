# Home Lab Hub redesign — first implementation

This branch starts from RaidOwl's original app. It does not include the scanner fork.

## Included

- Overview landing page with live inventory counts (not health monitoring), host reference/map links, record-name/address search and recently edited records.
- New header, sidebar, SVG favicon, browser title and light/dark theme.
- Settings for site name and theme.
- Maps scoped to a hardware host and its placement descendants.
- Shared type/search/depth filters for graph and tree; parent context retained.
- Named saved views and custom cross-host record selections.
- Wrapped graph layers and readable initial zoom, with explicit Fit all and Auto layout controls.
- Tree text contrast fix, orphan-safe tree construction, cycle-safe placement traversal, and direct inventory record links.
- Original-format inventory/document imports and existing database schema retained.

## Current boundaries

Saved map definitions, map positions, theme and site name are **browser-local**, per origin. They are not in JSON exports or shared between browsers. Clearing site data removes them. Changing from a port URL to a hostname gives a different browser preference store.

This is a first implementation. The inventory still uses the existing VM/runtime and application types. It does not yet distinguish Docker containers from other apps with structured subtype fields. Type filtering uses those existing types. Device categories, status filtering, group collapse, server-backed maps and a relationship editor are later milestones.

Custom maps select existing records; edges are shown only if relationships already exist in inventory. Selecting Ollama and Open WebUI does not invent a dependency. Placement links define host scope and tree hierarchy; dependency/manual links remain in graph view. Parent context can remain visible despite its type filter being unchecked.

The map layout uses up to eight nodes per row and a minimum initial readable zoom. Large maps may need scrolling/panning. Fit all deliberately allows smaller nodes. Map positions are separate from the original global server layout, which remains untouched.

## Local checks

From the frontend folder:

```sh
npm ci
npm test
npm run build
```

`npm test` uses Node's test runner for host isolation, ancestor context, custom membership, depth, cycles/orphans and wrapping large layers.

The frontend uses the original API endpoints. For local development run the backend on 127.0.0.1:5001 and `npm run dev` in frontend. Keep application databases, inventory exports, configuration secrets and deployment data outside the Git checkout.

## Test deployment on Betty

After pushing the branch from Windows, clone your fork on Betty into a new source directory:

```sh
git clone --branch feature/homelab-redesign --single-branch https://github.com/smith844/homelab-hub.git /mnt/cache/appdata/homelab-hub-redesign-source
docker build -t homelab-hub-redesign:test /mnt/cache/appdata/homelab-hub-redesign-source
ss -lntp 'sport = :8790'
```

If 8790 is free, create a separate test instance. This original-based app does not need Nmap or host networking:

```sh
docker run -d \
  --name homelab-hub-redesign \
  -p 8790:8000 \
  -v /mnt/cache/appdata/homelab-hub-redesign-data:/data \
  --restart unless-stopped \
  homelab-hub-redesign:test
```

Open http://192.168.1.80:8790 and import a copy of your inventory there. Existing original and scanner instances use different data folders and are not modified.

For subsequent changes, commit/push the Windows checkout, pull the branch in Betty's redesign source, rebuild the image and recreate only this test container with the same redesign data mount. Do not delete its data folder.

## Manual acceptance checks

1. Import an original JSON export into the separate test instance; open hosts, applications and documents.
2. Check Overview counts and host map links against imported inventory.
3. Open Betty's map, filter Applications, switch to Tree and inspect a device's text/values in both themes.
4. Save a named map, reload and reselect it. Test a custom selection across two hosts.
5. Change site name/theme and check browser title and favicon.
6. Test narrow/mobile layout and large graphs; verify no values are hidden by the detail panel.

Automated production compilation, Node map tests and a Flask import/API smoke test were completed during preparation. An automated browser session was unavailable; visual acceptance in the test instance is still required.
