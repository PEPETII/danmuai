import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createAutoSave } from '../web/static/modules/auto-save.js';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test('auto-save debounces edits and serializes the newest snapshot', async () => {
  let value = 'first';
  let activeRequests = 0;
  let maxActiveRequests = 0;
  const requests = [];
  const applied = [];
  const resolvers = [];
  const states = [];

  const autoSave = createAutoSave({
    delay: 5,
    capture: () => value,
    save: async (snapshot, { isLatest }) => {
      activeRequests += 1;
      maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
      requests.push(snapshot);
      await new Promise((resolve) => resolvers.push(resolve));
      if (isLatest()) applied.push(snapshot);
      activeRequests -= 1;
    },
    onState: (state) => states.push(state),
  });

  autoSave.schedule();
  value = 'latest-before-request';
  autoSave.schedule();
  await wait(20);
  assert.deepEqual(requests, ['latest-before-request']);

  value = 'latest-during-request';
  autoSave.schedule();
  resolvers.shift()();
  await wait(10);
  assert.deepEqual(requests, ['latest-before-request', 'latest-during-request']);
  resolvers.shift()();
  await autoSave.flush();

  assert.equal(maxActiveRequests, 1);
  assert.deepEqual(applied, ['latest-during-request']);
  assert.equal(states.filter((state) => state === 'saved').length, 1);
});

test('auto-save keeps a failed value dirty and retries after the next edit', async () => {
  let value = 'failed';
  let calls = 0;
  const autoSave = createAutoSave({
    capture: () => value,
    save: async (snapshot) => {
      calls += 1;
      if (calls === 1) throw new Error(`failed: ${snapshot}`);
    },
  });

  autoSave.schedule({ immediate: true });
  await assert.rejects(autoSave.flush(), /failed: failed/);
  assert.equal(calls, 1);

  value = 'retry';
  autoSave.schedule({ immediate: true });
  await autoSave.flush();
  assert.equal(calls, 2);
});

test('auto-save can invalidate a pending snapshot before switching records', async () => {
  let value = 'old';
  const requests = [];
  const autoSave = createAutoSave({
    delay: 5,
    capture: () => value,
    save: async (snapshot) => {
      requests.push(snapshot);
    },
  });

  autoSave.schedule();
  autoSave.cancel();
  value = 'new';
  autoSave.schedule({ immediate: true });
  await autoSave.flush();

  assert.deepEqual(requests, ['new']);
});
