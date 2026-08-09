import assert from 'node:assert/strict';
import { test } from 'node:test';

globalThis.window = {
  clearInterval() {},
  setInterval() {
    return 1;
  },
};

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }

  toggle(name, force) {
    const next = force === undefined ? !this.values.has(name) : Boolean(force);
    if (next) this.values.add(name);
    else this.values.delete(name);
    return next;
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.classList = new FakeClassList();
    this.dataset = {};
    this.children = [];
    this.textContent = '';
    this.value = '';
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  replaceChildren(...nodes) {
    this.children = nodes;
  }

  addEventListener() {}

  setAttribute() {}

  focus() {}
}

class FakeDocument {
  constructor() {
    this.elements = new Map();
    this.reset();
  }

  reset() {
    this.elements.clear();
    [
      'knowledgeJobList',
      'knowledgeJobEmpty',
      'knowledgeBackgroundJobBanner',
      'knowledgeBackgroundJobText',
      'knowledgeOrganizeStage',
      'knowledgeOrganizeModalDesc',
      'knowledgeOrganizeStatusLive',
      'knowledgeOrganizeResult',
      'knowledgeOrganizeProgressBar',
      'knowledgeOrganizeProgressIndeterminate',
      'knowledgeOrganizeActionsActive',
      'knowledgeOrganizeActionsDone',
      'knowledgeOrganizeActionsFailed',
      'knowledgeOrganizeTechnical',
      'knowledgeOrganizeTechnicalPre',
      'knowledgeOverviewName',
      'knowledgeOverviewStatusBadge',
      'knowledgeOverviewStats',
      'knowledgeOverviewSaveStatus',
    ].forEach((id) => this.elements.set(id, new FakeElement('div')));
  }

  getElementById(id) {
    return this.elements.get(id);
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }

  querySelectorAll() {
    return [];
  }
}

const document = new FakeDocument();
globalThis.document = document;

const jobsModule = await import('../web/static/modules/app-knowledge-jobs.js');
const state = await import('../web/static/modules/app-knowledge-state.js');
const { API } = await import('../web/static/modules/transport.js');

API.base = 'http://danmu.test';
API.token = 'contract-test-token';

let currentJobs = [];
let itemRequestCount = 0;
let packageRequestCount = 0;

globalThis.fetch = async (url) => {
  const path = new URL(url).pathname;
  if (path === '/api/knowledge/jobs') {
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ jobs: currentJobs }),
    };
  }
  if (path === '/api/knowledge/items') {
    itemRequestCount += 1;
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ items: [], total: 0, page: 1, page_size: 50 }),
    };
  }
  if (path === '/api/knowledge/packages/pkg') {
    packageRequestCount += 1;
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({
        public_id: 'pkg',
        name: 'Package',
        enabled: false,
        sources: [],
        items: { total: 3 },
      }),
    };
  }
  throw new Error(`Unexpected contract-test request: ${url}`);
};

const TERMINAL_CASES = [
  { status: 'completed', generated_items: 2 },
  { status: 'completed_with_errors', generated_items: 2, failed_chunks: 1 },
  { status: 'failed', generated_items: 0, error_message: 'failed' },
  { status: 'cancelled', generated_items: 0 },
];

function prepareCase(modalOpen, terminalJob) {
  document.reset();
  state.resetPackageContext();
  state.setCurrentPackageId('pkg');
  state.setCurrentPackageSnapshot({
    public_id: 'pkg',
    name: 'Package',
    enabled: false,
    source_count: 1,
    item_count: 0,
  });
  state.resetPreviousJobStatuses();
  state.previousJobStatusById.set('job', 'running');
  state.notifiedTerminalJobIds.clear();
  state.setOrganizeModalOpen(modalOpen);
  state.setOrganizeModalJobId(modalOpen ? 'job' : null);

  const progressBar = document.getElementById('knowledgeOrganizeProgressBar');
  progressBar.classList.remove('hidden');

  itemRequestCount = 0;
  packageRequestCount = 0;
  currentJobs = [{
    public_id: 'job',
    source_id: 'source',
    stage: 'finished',
    ...terminalJob,
  }];
}

test('terminal job refresh handles modal open and closed states', async () => {
  for (const modalOpen of [true, false]) {
    for (const terminalJob of TERMINAL_CASES) {
      prepareCase(modalOpen, terminalJob);
      await jobsModule.refreshJobs();

      assert.equal(
        itemRequestCount,
        1,
        `${modalOpen ? 'open' : 'closed'} ${terminalJob.status} should refresh items once`,
      );
      assert.equal(
        packageRequestCount,
        1,
        `${modalOpen ? 'open' : 'closed'} ${terminalJob.status} should refresh package overview once`,
      );
      assert.equal(
        state.currentPackageSnapshot?.item_count,
        3,
        `${modalOpen ? 'open' : 'closed'} ${terminalJob.status} should apply the refreshed package snapshot`,
      );
      assert.notEqual(
        document.getElementById('knowledgeOverviewStats').textContent,
        '',
        `${modalOpen ? 'open' : 'closed'} ${terminalJob.status} should update overview`,
      );

      if (!modalOpen) continue;

      assert.notEqual(
        document.getElementById('knowledgeOrganizeResult').textContent,
        '',
        `${terminalJob.status} should update the open modal result`,
      );
      const expectedActions =
        terminalJob.status === 'failed' || terminalJob.status === 'cancelled'
          ? 'knowledgeOrganizeActionsFailed'
          : 'knowledgeOrganizeActionsDone';
      assert.equal(
        document.getElementById(expectedActions).classList.contains('hidden'),
        false,
        `${terminalJob.status} should select its terminal action group`,
      );
      if (terminalJob.status === 'completed') {
        assert.equal(
          document.getElementById('knowledgeOrganizeProgressBar').classList.contains('hidden'),
          true,
          'completed should hide the determinate progress bar',
        );
      }
    }
  }
});
