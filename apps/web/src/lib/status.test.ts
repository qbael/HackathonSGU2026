import assert from 'node:assert/strict';
import test from 'node:test';
import { readSystemStatus } from './status.ts';

test('accepts actual scaffold readiness without inventing availability', () => {
  const value = {
    name: 'Findie API',
    stage: 'scaffold',
    database: 'ready',
    ai: 'unavailable',
    features: { business: false, authentication: false, storage: false },
  };
  assert.deepEqual(readSystemStatus(value), value);
  const identityEnabled = { ...value, features: { ...value.features, authentication: true } };
  assert.deepEqual(readSystemStatus(identityEnabled), identityEnabled);
  const businessEnabled = { ...value, features: { business: true, authentication: true, storage: true } };
  assert.deepEqual(readSystemStatus(businessEnabled), businessEnabled);
});

test('rejects non-boolean authentication flags', () => {
  for (const authentication of [undefined, null, 0, 1, 'false', 'true', {}, []]) {
    assert.throws(() => readSystemStatus({
      name: 'Findie API',
      stage: 'scaffold',
      database: 'ready',
      ai: 'unavailable',
      features: { business: false, authentication, storage: false },
    }));
  }
});

test('rejects malformed or unexpected API responses', () => {
  for (const value of [null, [], {}, 'ready', { database: 'ready' }, {
    name: 'Findie API',
    stage: 'scaffold',
    database: 'ready',
    ai: 'unknown',
    features: { business: false, authentication: false, storage: false },
  }]) {
    assert.throws(() => readSystemStatus(value));
  }
});
