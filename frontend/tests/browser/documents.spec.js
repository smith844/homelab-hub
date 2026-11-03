import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const title = 'Betty — Docker applications, storage paths and recovery reference';
async function setup(page, {theme='dark',failSave=false}={}) {
  const docs = [{id:1,title,content:'# Service notes\n\nUseful notes for Betty.\n\n## Configuration\n\n- DNS\n- Storage\n\n| Setting | Value |\n| --- | --- |\n| Host | Betty |\n\n```sh\nprintf "<configuration>"\n```'}, {id:2,title:'Blackbox — Proxmox backup and restore',content:'## Recovery\n\nSecond document.'}];
  const writes=[];
  await page.addInitScript(theme => localStorage.setItem('hlh.theme',JSON.stringify(theme)),theme);
  await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({contentType:'text/css',body:readFileSync('node_modules/@picocss/pico/css/pico.min.css')}));
  await page.route('**/api/docs**',async route=>{
    const request=route.request(), match=new URL(request.url()).pathname.match(/\/docs\/(\d+)$/);
    const doc=match ? docs.find(d=>d.id===Number(match[1])) : null;
    if(request.method()==='POST') {const doc={id:3,title:'Untitled',content:''};docs.push(doc);return route.fulfill({status:201,json:{data:doc}});}
    if(request.method()==='PUT') {
      writes.push({id:doc.id,...request.postDataJSON()});
      if(failSave) return route.fulfill({status:500,json:{error:'Save unavailable'}});
      Object.assign(doc,request.postDataJSON()); return route.fulfill({json:{data:doc}});
    }
    if(request.method()==='DELETE') {docs.splice(docs.indexOf(doc),1);return route.fulfill({json:{message:'Deleted'}});}
    return route.fulfill({json:{data:doc||docs}});
  });
  await page.goto('/#/docs/1');
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
  return {docs,writes};
}
for(const theme of ['light','dark']) test(`${theme}: reading first, full titles and Markdown structure`,async({page})=>{
  await page.setViewportSize({width:1440,height:1000});
  await setup(page,{theme});
  await expect(page.getByRole('button',{name:'Edit document',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Rich Text',exact:true})).toHaveCount(0);
  const link=page.getByRole('link',{name:title,exact:true});
  expect(await link.evaluate(el=>getComputedStyle(el).whiteSpace)).toBe('normal');
  await expect(page.locator('.document-body table')).toBeVisible();
  await expect(page.locator('.document-body ul li')).toHaveCount(2);
  await expect(page.locator('.document-body pre code')).toContainText('<configuration>');
  await expect(page.locator('.document-body configuration')).toHaveCount(0);
  await page.screenshot({path:`test-results/documents-${theme}.png`,fullPage:true});
});
test('search, drag/keyboard resize and remembered width',async({page})=>{
  await page.setViewportSize({width:1600,height:1000}); await setup(page);
  const divider=page.getByRole('separator',{name:'Resize document list'});
  await divider.focus(); await page.keyboard.press('ArrowRight');
  await expect(divider).toHaveAttribute('aria-valuenow','360');
  const box=await divider.boundingBox();
  await page.mouse.move(box.x+3,box.y+100);await page.mouse.down();await page.mouse.move(box.x+63,box.y+100);await page.mouse.up();
  await expect(divider).toHaveAttribute('aria-valuenow','420');
  await page.reload();await expect(divider).toHaveAttribute('aria-valuenow','420');
  await page.getByRole('searchbox',{name:'Find a document'}).fill('Blackbox');
  await expect(page.getByRole('navigation',{name:'Document list'}).getByRole('link')).toHaveCount(1);
});
test('switching documents immediately saves the correct document',async({page})=>{
  const {writes}=await setup(page);
  await page.getByRole('button',{name:'Edit document',exact:true}).click();
  await page.getByRole('textbox',{name:'Document Markdown'}).fill('Updated Betty notes');
  await page.getByRole('link',{name:'Blackbox — Proxmox backup and restore',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Blackbox — Proxmox backup and restore',exact:true})).toBeVisible();
  await expect.poll(()=>writes.length).toBe(1);
  expect(writes[0]).toMatchObject({id:1,content:'Updated Betty notes'});
  await expect(page.locator('.document-body')).toContainText('Second document.');
});
test('failed saves remain visible and survive leaving the Documents page',async({page})=>{
  await setup(page,{failSave:true});
  await page.getByRole('button',{name:'Edit document',exact:true}).click();
  await page.getByRole('textbox',{name:'Document Markdown'}).fill('Retain this draft');
  await expect(page.getByRole('status')).toHaveText('Save failed');
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Settings',exact:true}).click();
  await page.goto('/#/docs/1');
  await expect(page.locator('.document-body')).toContainText('Retain this draft');
  await expect(page.getByRole('button',{name:'Retry save',exact:true})).toBeVisible();
});
test('title edits, Done editing, rich text and safe deletion remain available',async({page})=>{
  const {docs}=await setup(page);
  const originalContent = docs[0].content;
  await page.getByRole('button',{name:'Edit document',exact:true}).click();
  await page.getByRole('textbox',{name:'Document title'}).fill('Renamed reference');
  await page.getByRole('button',{name:'Rich Text',exact:true}).click();
  await expect(page.locator('.richtext-editor')).toBeVisible();
  await page.getByRole('button',{name:'Done editing',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Renamed reference',exact:true})).toBeVisible();
  expect(docs[0].title).toBe('Renamed reference');
  expect(docs[0].content).toBe(originalContent);
  await page.getByRole('button',{name:'Document actions',exact:true}).click();
  page.once('dialog',dialog=>dialog.dismiss());
  await page.getByRole('button',{name:'Delete document…',exact:true}).click();
  expect(docs).toHaveLength(2);
});
test('narrow screens keep document titles and content accessible',async({page})=>{
  await page.setViewportSize({width:390,height:844});await setup(page);
  await expect(page.getByRole('separator')).toBeHidden();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('new notes open for editing and successful deletion returns to the document list',async({page})=>{
  const {docs}=await setup(page);
  await page.getByRole('button',{name:'+ New',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Document title'})).toHaveValue('Untitled');
  await page.getByRole('textbox',{name:'Document Markdown'}).fill('A new note');
  await page.getByRole('button',{name:'Done editing',exact:true}).click();
  await expect(page.locator('.document-body')).toHaveText('A new note');
  await page.getByRole('button',{name:'Document actions',exact:true}).click();
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Delete document…',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your homelab knowledge, in one place'})).toBeVisible();
  expect(docs).toHaveLength(2);
});
test('rendered notes sanitise active HTML and unsafe link targets',async({page})=>{
  await setup(page);
  await page.getByRole('button',{name:'Edit document',exact:true}).click();
  await page.getByRole('textbox',{name:'Document Markdown'}).fill('<script>window.noteScriptRan=true</script>\n\n<img src="missing" onerror="window.noteScriptRan=true">\n\n[Unsafe](javascript:alert(1))');
  await page.getByRole('button',{name:'Done editing',exact:true}).click();
  await expect(page.locator('.document-body script, .document-body [onerror], .document-body a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(()=>window.noteScriptRan)).toBeUndefined();
});
