import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDocumentSaves } from '../src/lib/documentSaves.js';

test('switching documents saves each captured draft to its own ID', async () => {
  const writes = [];
  const saves = createDocumentSaves(async (id, draft) => writes.push({id, ...draft}), () => {}, 10000);
  const a = {title:'A',content:'First edit'};
  saves.update(1,a); a.content = 'Unrelated mutation';
  saves.update(2,{title:'B',content:'Second edit'});
  await saves.flushAll();
  assert.deepEqual(writes,[{id:1,title:'A',content:'First edit'},{id:2,title:'B',content:'Second edit'}]);
  assert.deepEqual(saves.unsaved(),[]);
});
test('edits made during an in-flight save are serialised', async () => {
  let release;
  const writes = [];
  const saves = createDocumentSaves(async (id, draft) => {
    writes.push(draft.content);
    if (writes.length === 1) await new Promise(resolve => release = resolve);
  }, () => {},10000);
  saves.update(1,{title:'A',content:'Older'});
  const running = saves.flush(1);
  saves.update(1,{title:'Renamed',content:'Newest'});
  release(); await running; await saves.flush(1);
  assert.deepEqual(writes,['Older','Newest']);
  assert.equal(saves.state(1),'saved');
});
test('failed saves retain drafts and can be retried', async () => {
  let fail = true;
  const saves = createDocumentSaves(async () => {if(fail) throw Error('offline');}, () => {},10000);
  saves.update(1,{title:'A',content:'Keep this'});
  assert.equal(await saves.flush(1),false);
  assert.equal(saves.state(1),'error');
  assert.equal(saves.draft(1).content,'Keep this');
  assert.deepEqual(saves.unsaved(),[1]);
  fail = false;
  assert.equal(await saves.flush(1),true);
  assert.equal(saves.state(1),'saved');
});
