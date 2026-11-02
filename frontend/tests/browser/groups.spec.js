import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=', 'base64');
const group = {id: 7, name: 'Media', source: 'folderview', host_key: 'betty', external_id: 'media', active: true, sort_order: 0, icon: 'https://icons.example/icon.png', assignment_count: 1, override_count: 0, unmatched_count: 0};
const graph = {nodes: [
  {data: {id: 'hardware-1', type: 'hardware', entity_id: 1, rawName: 'Betty', label: 'Betty'}},
  {data: {id: 'apps-1', type: 'apps', entity_id: 1, rawName: 'Plex', label: 'Plex'}},
], edges: [{data: {id: 'e1', source: 'hardware-1', target: 'apps-1', relation: 'placement'}}]};

async function setup(page, theme) {
  await page.addInitScript(theme => { localStorage.setItem('hlh.theme', JSON.stringify(theme)); sessionStorage.setItem('hlh.adminToken', 'browser-test'); }, theme);
  await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({contentType: 'text/css', body: readFileSync('node_modules/@picocss/pico/css/pico.min.css')}));
  await page.route('https://icons.example/**', route => route.fulfill({contentType: 'image/png', body: png, headers: {'Access-Control-Allow-Origin': '*'}}));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    let json = {data: []};
    if (path.endsWith('/management')) json = {hosts: [{key: 'betty', label: 'Betty'}], groups: [group], apps: [], unmatched: []};
    if (path.endsWith('/graph')) json = graph;
    if (path.endsWith('/effective')) json = {groups: [group], memberships: [{group_id: 7, host_key: 'betty', app_id: 1}], unmatched: [], ungrouped_apps: []};
    if (path.endsWith('/sync')) json = {dry_run: true, folders: {total: 1}, groups: {created: 0, updated: 1, reactivated: 0, unchanged: 0, archived: 0}, assignments: {added: 0, moved: 0, removed: 0, unchanged: 1}, overrides: {untouched: 1}, conflicts: [], warnings: [], unmatched_containers: [], ungrouped_apps: [], group_changes: [{name: 'Media', external_id: 'media', action: 'update', fields: [{field: 'source_metadata.updatedAt', before: 'yesterday', after: 'today'}], preserved: [{field: 'icon', local: '🎬', incoming: group.icon}]}]};
    return route.fulfill({json});
  });
}

async function readable(locator, centred = true) {
  const metrics = () => locator.evaluate(el => {
    const rgb = value => value.match(/[\d.]+/g).slice(0,3).map(Number);
    const style = getComputedStyle(el);
    let bg = style.backgroundColor;
    let parent = el;
    while (bg === 'rgba(0, 0, 0, 0)' && parent.parentElement) { parent = parent.parentElement; bg = getComputedStyle(parent).backgroundColor; }
    const lum = color => rgb(color).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }).reduce((s,v,i) => s + v * [.2126,.7152,.0722][i],0);
    const a=lum(style.color),b=lum(bg);
    return {ratio: (Math.max(a,b)+.05)/(Math.min(a,b)+.05), align: style.alignItems};
  });
  // The selector animates foreground/background for 150 ms. Assert the settled
  // rendered state rather than sampling an arbitrary intermediate frame.
  await expect.poll(async () => (await metrics()).ratio).toBeGreaterThanOrEqual(4.5);
  if (centred) expect((await metrics()).align).toBe('center');
}

for (const theme of ['light', 'dark']) {
  test(`${theme}: images, fallbacks, centred buttons and field preview`, async ({page}) => {
    await setup(page, theme);
    await page.goto('/#/groups');
    const image = page.locator('.group-icon img');
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate(el => el.naturalWidth)).toBeGreaterThan(0);
    for (const label of ['Save token', 'Create group']) await readable(page.getByRole('button', {name: label, exact: true}));
    await page.getByRole('button', {name: 'Edit', exact: true}).click();
    const save = page.getByRole('button', {name: 'Save', exact: true});
    await readable(save);
    // The text line box must fit and be centred inside each fixed-height button.
    for (const button of [save, page.getByRole('button', {name: 'Create group', exact: true})]) {
      const metrics = await button.evaluate(el => {const s=getComputedStyle(el);const r=document.createRange();r.selectNodeContents(el); const text=r.getBoundingClientRect(), box=el.getBoundingClientRect();return {delta: Math.abs((text.top+text.bottom-box.top-box.bottom)/2), fits: parseFloat(s.lineHeight)+parseFloat(s.paddingTop)+parseFloat(s.paddingBottom)+2*parseFloat(s.borderTopWidth)<=box.height+1};});
      expect(metrics.fits).toBe(true);
      expect(metrics.delta).toBeLessThan(3);
    }
    await page.getByRole('button', {name: 'Preview sync', exact: true}).click();
    await expect(page.getByRole('cell', {name: 'source_metadata.updatedAt', exact: true})).toBeVisible();
    await expect(page.getByRole('cell', {name: 'yesterday', exact: true})).toBeVisible();
    await expect(page.getByRole('cell', {name: 'today', exact: true})).toBeVisible();
    await expect(page.getByText('icon — local choice preserved.', {exact: true})).toBeVisible();
    await image.dispatchEvent('error');
    await expect(page.locator('.group-icon')).toHaveText('📁');
  });

  test(`${theme}: map selector states and grouped canvas image`, async ({page}) => {
    await setup(page, theme);
    await page.goto('/#/map');
    const selector = page.getByRole('group', {name: 'Map presentation'});
    for (const label of ['Graph', 'Grouped', 'Tree']) {
      const button = selector.getByRole('button', {name: label, exact: true});
      await readable(button);
      await button.hover(); await readable(button);
      await button.focus(); await expect(button).toBeFocused(); await readable(button);
      await button.click(); await readable(button);
    }
    await selector.getByRole('button', {name: 'Grouped', exact: true}).click();
    for (const button of ['Save view', 'Auto layout', 'Fit all', 'Readable zoom', 'Expand map']) {
      await readable(page.getByRole('button', {name: button, exact: true}));
    }
    for (const control of await page.locator('.map-toolbar select, .map-toolbar input').all()) await readable(control, false);
    await expect(page.locator('.cy-container canvas').first()).toBeVisible();
    // Inspect Cytoscape's actual rendered card data/style, not just source strings.
    const card = await page.locator('.cy-container').evaluate(el => {
      const cy = el._cyreg.cy;
      const node = cy.nodes('[type="group"]').first();
      return {label: node.data('label'), image: node.style('background-image'), width: node.width()};
    });
    expect(card.label).toContain('Media');
    expect(card.label).not.toContain('https:');
    expect(card.image).toContain(group.icon);
    expect(card.width).toBe(220);
  });
}

for (const theme of ['light', 'dark']) {
  test(`${theme}: grouped icon and wrapped label occupy separate areas through expansion`, async ({page}) => {
    await setup(page, theme);
    const names = ['Hosting', 'IAM and Security', 'AI', 'Infrastructure and Monitoring Services'];
    const groups = names.map((name, i) => ({...group, id: 7 + i, name}));
    const apps = names.map((_, i) => ({data: {id: `apps-${i + 1}`, type: 'apps', entity_id: i + 1, rawName: `App ${i + 1}`, label: `App ${i + 1}`}}));
    await page.route('**/api/map/graph', route => route.fulfill({json: {
      nodes: [graph.nodes[0], ...apps],
      edges: apps.map(app => ({data: {id: `edge-${app.data.id}`, source: 'hardware-1', target: app.data.id, relation: 'placement'}})),
    }}));
    await page.route('**/api/container-groups/effective', route => route.fulfill({json: {
      groups, memberships: groups.map((g, i) => ({group_id: g.id, host_key: 'betty', app_id: i + 1})), unmatched: [], ungrouped_apps: [],
    }}));
    await page.goto('/#/map');
    await page.getByRole('button', {name: 'Grouped', exact: true}).click();
    const canvas = page.locator('.cy-container');
    await expect.poll(() => canvas.evaluate(el => el._cyreg.cy.nodes('[type="group"]').length)).toBe(4);

    const measure = () => canvas.evaluate(el => {
      const cy = el._cyreg.cy;
      return cy.nodes('[type="group"]').map(node => {
        const label = node.boundingBox({includeNodes: false, includeEdges: false, includeLabels: true, includeOverlays: false});
        const top = node.position('y') - node.height() / 2;
        return {id: node.id(), width: node.width(), height: node.height(),
          label: node.style('label'), labelTop: label.y1 - top, labelBottom: label.y2 - top,
          labelWidth: label.w, imageX: node.style('background-position-x'),
          imageTop: parseFloat(node.style('background-position-y')),
          imageHeight: parseFloat(node.style('background-height')), imageFit: node.style('background-fit'),
          expanded: node.data('expanded'), position: {...node.position()}};
      });
    });
    const checkAreas = cards => {
      for (const card of cards) {
        expect(card.width).toBe(220);
        expect(card.height).toBe(92);
        expect(card.imageX).toBe('50%');
        expect(card.imageFit).toBe('none');
        expect(card.labelTop).toBeGreaterThan(card.imageTop + card.imageHeight + 4);
        expect(card.labelBottom).toBeLessThan(90);
        expect(card.labelWidth).toBeLessThan(200);
        expect(card.label).toMatch(/\n1 member$/);
      }
    };
    // Inspect actual raster output as well as declared image geometry: contain
    // scales a 1px fixture to the full card despite explicit background dimensions.
    const whitePixels = () => canvas.evaluate(async el => {
      const image = new Image();
      image.src = el._cyreg.cy.png({full: true, scale: 1, bg: '#000000'});
      await image.decode();
      const target = document.createElement('canvas');
      target.width = image.width; target.height = image.height;
      const context = target.getContext('2d'); context.drawImage(image, 0, 0);
      const pixels = context.getImageData(0, 0, target.width, target.height).data;
      let white = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === 255 && pixels[i + 1] === 255 && pixels[i + 2] === 255) white++;
      }
      return white;
    });
    await expect.poll(whitePixels).toBeGreaterThan(1900);
    expect(await whitePixels()).toBeLessThan(2705); // Four 24 x 24 icons, allowing antialiasing.
    const collapsed = await measure();
    checkAreas(collapsed);
    expect(collapsed.every(card => card.expanded === false)).toBe(true);
    expect(collapsed[3].labelBottom - collapsed[3].labelTop).toBeGreaterThan(30);

    // Use the existing drag handler to establish a real persisted manual anchor.
    await canvas.evaluate(el => {
      const node = el._cyreg.cy.getElementById('group-8@betty');
      node.position({x: 600, y: 420}); node.emit('dragfree'); node.emit('tap');
    });
    await expect.poll(async () => (await measure()).find(card => card.id === 'group-8@betty').expanded).toBe(true);
    const expanded = await measure();
    checkAreas(expanded);
    expect(expanded.find(card => card.id === 'group-8@betty').position).toEqual({x: 600, y: 420});
    const connections = await canvas.evaluate(el => {
      const cy = el._cyreg.cy;
      return {parents: cy.edges('.group-parent-edge').length,
        members: cy.edges('.group-member-edge').length,
        memberVisible: cy.getElementById('apps-2').style('display') !== 'none'};
    });
    expect(connections).toEqual({parents: 4, members: 1, memberVisible: true});
    await canvas.evaluate(el => el._cyreg.cy.getElementById('group-8@betty').emit('tap'));
    checkAreas(await measure());
    await page.reload();
    await expect.poll(async () => (await measure()).find(card => card.id === 'group-8@betty')?.position).toEqual({x: 600, y: 420});
    checkAreas(await measure());
    await page.screenshot({path: `/tmp/hlh-grouped-card-${theme}.png`, fullPage: true});
    await page.getByRole('button', {name: 'Graph', exact: true}).click();
    await expect.poll(() => canvas.evaluate(el => {
      const cy = el._cyreg.cy;
      return {groups: cy.nodes('[type="group"]').length, appHeight: cy.getElementById('apps-1').height()};
    })).toEqual({groups: 0, appHeight: 48});
  });
}
