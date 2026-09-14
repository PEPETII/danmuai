/**
 * 知识库 API 错误协议回归（Case F/G）。
 *
 * 背景：``/api/knowledge/*`` 过去用 ``200 + {"error": "xxx"}`` 表示失败，
 * 前端因此会把失败当成功（"创建/删除成功"、清空输入、轮询不存在的 job）。
 * 修复后非 2xx 由 ``transport.apiFetch()`` 抛错；本文件锁定三件事：
 *
 *   1. ``assertKnowledgePayload()`` 必须对残留的 ``200 + {error}`` 抛错，
 *      且抛出的 Error 带 ``code`` 供调用方区分；
 *   2. ``knowledgeErrorMessage()`` 必须把错误码翻译成文案，且绝不把
 *      ``notFound`` 这类 i18n 伪键泄漏给用户；
 *   3. 路由层 ``_KNOWLEDGE_ERROR_STATUSES`` 的每个错误码都必须在
 *      ``KNOWLEDGE_API_ERROR_KEYS`` 与 zh/en 两份 locale 中都有对应文案。
 *
 * 运行时无并发副作用；不访问网络、不写磁盘。
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

globalThis.window = {};
globalThis.document = {
  getElementById: () => null,
  querySelectorAll: () => [],
  createElement: () => ({}),
  addEventListener() {},
};

const status = await import('../web/static/modules/app-knowledge-status.js');
const { KNOWLEDGE_API_ERROR_KEYS, assertKnowledgePayload, humanizeKnowledgeApiError, knowledgeErrorMessage } =
  status;

const REPO = new URL('../', import.meta.url);

function readJson(relPath) {
  return JSON.parse(readFileSync(new URL(relPath, REPO), 'utf8'));
}

// --------------------------------------------------------------------------
// 1. assertKnowledgePayload —— 业务失败不得被当作成功
// --------------------------------------------------------------------------

test('assertKnowledgePayload throws a coded error on residual 200 + {error}', () => {
  for (const code of ['not_found', 'orchestrator_stopping', 'not_initialized']) {
    assert.throws(
      () => assertKnowledgePayload({ error: code }),
      (err) => {
        assert.equal(err.code, code, `error.code should carry the business code for ${code}`);
        assert.ok(err instanceof Error);
        assert.ok(err.message.length > 0, 'message must not be empty (no silent failure)');
        return true;
      },
      `payload {"error": "${code}"} must throw`,
    );
  }
});

test('assertKnowledgePayload passes through genuine success payloads unchanged', () => {
  const successCases = [
    { ok: true, package_id: 'pk_abc' },
    { ok: true, job_id: 'kj_1' },
    { ok: true },
    { packages: [], total: 0 },
    { jobs: [] },
    { items: [], total: 0, page: 1 },
  ];
  for (const payload of successCases) {
    assert.deepEqual(assertKnowledgePayload(payload), payload);
  }
});

test('assertKnowledgePayload tolerates empty error and non-object payloads', () => {
  // 空字符串 / 非字符串的 error 不是业务失败信号。
  assert.deepEqual(assertKnowledgePayload({ ok: true, error: '' }), { ok: true, error: '' });
  assert.deepEqual(assertKnowledgePayload({ ok: true, error: null }), { ok: true, error: null });
  // 数组与原始值不受影响（数组没有 error 语义）。
  assert.deepEqual(assertKnowledgePayload([{ error: 'not_found' }]), [{ error: 'not_found' }]);
  assert.equal(assertKnowledgePayload(null), null);
  assert.equal(assertKnowledgePayload(undefined), undefined);
  assert.equal(assertKnowledgePayload('plain'), 'plain');
  assert.equal(assertKnowledgePayload(0), 0);
});

// --------------------------------------------------------------------------
// 2. knowledgeErrorMessage —— 永不泄漏 i18n 伪键
// --------------------------------------------------------------------------

test('knowledgeErrorMessage never leaks a bare i18n pseudo-key', () => {
  for (const code of Object.keys(KNOWLEDGE_API_ERROR_KEYS)) {
    const text = humanizeKnowledgeApiError(code);
    assert.ok(text.length > 0, `humanizeKnowledgeApiError(${code}) must not be empty`);
    // t() 在 locale 未加载时会退化成 key 末段（notFound / stopping ...），
    // 那种伪文案不能出现，至少要回退成原始错误码本身。
    assert.ok(
      !text.includes('apiErrors.'),
      `localized text for ${code} leaked the i18n key path: ${text}`,
    );
  }
});

test('knowledgeErrorMessage prefers mapped code, then message, then fallback', () => {
  // 已映射错误码：返回文案（此时 locale 未加载 → 回退成原始码，仍非空且非伪键）
  const mapped = knowledgeErrorMessage({ code: 'package_not_found' });
  assert.ok(mapped.length > 0);
  assert.equal(mapped, 'package_not_found');

  // 未映射错误码 + message：回退到 message
  assert.equal(knowledgeErrorMessage({ code: 'totally_unknown', message: 'boom' }), 'boom');

  // 无 code：回退到 message
  assert.equal(knowledgeErrorMessage({ message: 'network down' }), 'network down');

  // 什么都没有：回退到兜底文案
  assert.equal(knowledgeErrorMessage(null, 'fallback text'), 'fallback text');
  assert.equal(knowledgeErrorMessage({}, ''), '');
  assert.equal(knowledgeErrorMessage({ code: '' }, 'empty-code-fallback'), 'empty-code-fallback');
});

// --------------------------------------------------------------------------
// 3. 跨文件契约：路由错误码 ↔ 前端映射 ↔ zh/en 文案
// --------------------------------------------------------------------------

function routeErrorCodes() {
  const src = readFileSync(
    new URL('app/web_api/knowledge_routes.py', REPO),
    'utf8',
  );
  const block = src.match(/_KNOWLEDGE_ERROR_STATUSES\s*=\s*\{([\s\S]*?)\}/);
  assert.ok(block, 'could not locate _KNOWLEDGE_ERROR_STATUSES in knowledge_routes.py');
  const codes = [...block[1].matchAll(/"([a-z_]+)"\s*:\s*\d+/g)].map((m) => m[1]);
  assert.ok(codes.length >= 5, `expected several mapped codes, got ${codes.length}`);
  return codes;
}

function apiErrorLocaleValues(lang) {
  // dynamic.json 的顶层是 {"dynamic": {...}, "settingsHints": {...}}；
  // 运行时 t() 用的键是 `dynamic.appKnowledgePage.apiErrors.<name>`。
  const shard = readJson(`web/static/locales/${lang}/dynamic.json`);
  const block = shard?.dynamic?.appKnowledgePage?.apiErrors;
  assert.ok(block && typeof block === 'object', `${lang} dynamic.json missing dynamic.appKnowledgePage.apiErrors`);
  return block;
}

test('every route-mapped knowledge error code has a frontend mapping', () => {
  const missing = routeErrorCodes().filter((code) => !KNOWLEDGE_API_ERROR_KEYS[code]);
  assert.deepEqual(missing, [], `codes without frontend mapping: ${missing.join(', ')}`);
});

test('every frontend apiError key exists in both zh and en locales', () => {
  const zh = apiErrorLocaleValues('zh');
  const en = apiErrorLocaleValues('en');
  const keys = Object.keys(KNOWLEDGE_API_ERROR_KEYS).reduce((acc, code) => {
    acc.add(KNOWLEDGE_API_ERROR_KEYS[code]);
    return acc;
  }, new Set());
  const missingZh = [...keys].filter((k) => !zh[k]);
  const missingEn = [...keys].filter((k) => !en[k]);
  assert.deepEqual(missingZh, [], `zh missing apiErrors keys: ${missingZh.join(', ')}`);
  assert.deepEqual(missingEn, [], `en missing apiErrors keys: ${missingEn.join(', ')}`);
});
