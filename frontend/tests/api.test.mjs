import test from 'node:test';
import assert from 'node:assert/strict';
import { api, apiRequest, ApiError, DEFAULT_API_URL } from '../src/api/client.js';

const response = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });

test('POST /api/sessions: no request body, uses real endpoint', async () => {
  const old = global.fetch;
  let called;
  global.fetch = async (url, options) => { called = { url, options }; return response(201, { id: 'test-uuid', created_at: '2026-01-01T00:00:00Z' }); };
  try {
    assert.equal((await api.createSession()).id, 'test-uuid');
    assert.equal(called.url, `${DEFAULT_API_URL}/api/sessions`);
    assert.equal(called.options.method, 'POST');
    assert.equal(called.options.body, undefined);
  } finally { global.fetch = old; }
});

test('POST /api/chat follows existing FastAPI payload and answer field', async () => {
  const old = global.fetch;
  let called;
  global.fetch = async (url, options) => { called = { url, options }; return response(200, { session_id: 'abc', answer: 'Тестовый ответ', sources: [], intent: 'mock', latency_ms: 3 }); };
  try {
    const data = await api.chat('abc', 'Привет');
    assert.equal(data.answer, 'Тестовый ответ');
    assert.equal(called.url, `${DEFAULT_API_URL}/api/chat`);
    assert.deepEqual(JSON.parse(called.options.body), { session_id: 'abc', message: 'Привет' });
  } finally { global.fetch = old; }
});

test('GET messages uses role/content from existing endpoint', async () => {
  const old = global.fetch;
  global.fetch = async (url) => {
    assert.equal(url, `${DEFAULT_API_URL}/api/sessions/abc/messages`);
    return response(200, [{ id: 1, role: 'user', content: 'Привет' }, { id: 2, role: 'assistant', content: 'Здравствуйте' }]);
  };
  try { assert.equal((await api.getMessages('abc'))[1].content, 'Здравствуйте'); }
  finally { global.fetch = old; }
});

test('POST /api/leads uses consent_to_contact and snake_case keys', async () => {
  const old = global.fetch;
  let payload;
  global.fetch = async (url, options) => {
    assert.equal(url, `${DEFAULT_API_URL}/api/leads`);
    payload = JSON.parse(options.body);
    return response(201, { id: 'lead-test', session_id: 'abc' });
  };
  try {
    assert.equal((await api.createLead({ sessionId: 'abc', fullName: ' Test Name ', phone: ' +79990000000 ', company: ' ООО Тест ', consent: true })).id, 'lead-test');
    assert.deepEqual(payload, { session_id: 'abc', full_name: 'Test Name', phone: '+79990000000', company: 'ООО Тест', consent_to_contact: true });
  } finally { global.fetch = old; }
});

test('request exposes FastAPI 422 detail without inventing success', async () => {
  const old = global.fetch;
  global.fetch = async () => response(422, { detail: [{ msg: 'Field required' }] });
  try {
    await assert.rejects(() => apiRequest('/api/chat'), (err) => err instanceof ApiError && err.status === 422 && /Field required/.test(err.message));
  } finally { global.fetch = old; }
});

test('close session uses the implemented POST endpoint', async () => {
  const old = global.fetch;
  let called;
  global.fetch = async (url, options) => { called = { url, options }; return response(200, { closed: true }); };
  try {
    assert.equal((await api.closeSession('abc')).closed, true);
    assert.equal(called.url, `${DEFAULT_API_URL}/api/sessions/abc/close`);
    assert.equal(called.options.method, 'POST');
  } finally { global.fetch = old; }
});
