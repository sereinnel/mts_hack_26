import test from 'node:test';
import assert from 'node:assert/strict';
import { getRecentSessions, rememberSession, markSessionClosed, getActiveSessionId, setActiveSessionId, rememberLeadId, getSavedLeadId } from '../src/lib/storage.js';

const values = new Map();
global.localStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
};

test('stores only the session id and timestamp, not message contents', () => {
  rememberSession({ id: 's1', created_at: '2026-11-11T08:00:00Z', secret: 'should-not-be-saved' });
  assert.deepEqual(getRecentSessions(), [{ id: 's1', created_at: '2026-11-11T08:00:00Z', closed_at: null }]);
  assert.ok(!JSON.stringify([...values]).includes('should-not-be-saved'));
});

test('active session persists and old session can be marked closed without removal', () => {
  setActiveSessionId('s1');
  assert.equal(getActiveSessionId(), 's1');
  markSessionClosed('s1');
  assert.ok(getRecentSessions()[0].closed_at);
  assert.equal(getRecentSessions()[0].id, 's1');
});

test('lead ID memo is stored without PII', () => {
  rememberLeadId('s1', 'lead-1');
  assert.equal(getSavedLeadId('s1'), 'lead-1');
  assert.ok(!JSON.stringify([...values]).includes('phone'));
});
