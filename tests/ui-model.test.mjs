import test from 'node:test';
import assert from 'node:assert/strict';
import {usageColor, summaryQuota, countdown, mergeResult} from '../ui-model.js';

test('threshold boundaries and unknown consumption', () => {
    assert.equal(usageColor(0), 'normal');
    assert.equal(usageColor(69.9), 'normal');
    assert.equal(usageColor(70), 'warning');
    assert.equal(usageColor(89.9), 'warning');
    assert.equal(usageColor(90), 'critical');
    assert.equal(usageColor(100), 'critical');
    assert.equal(usageColor(null), 'unknown');
    assert.equal(usageColor(NaN), 'unknown');
});
test('panel prioritizes five-hour quota and never sums groups', () => {
    const quotas = [{windowMinutes: 300, usedPercent: 25}, {windowMinutes: 300, usedPercent: 60},
        {windowMinutes: 10080, usedPercent: 98}];
    assert.equal(summaryQuota(quotas).usedPercent, 60);
    assert.equal(summaryQuota([quotas[2]]).usedPercent, 98);
    assert.equal(summaryQuota([{usedPercent: null}]), null);
    assert.equal(summaryQuota([{usedPercent: 20, disabled: true}]), null);
});
test('countdown does not claim quota reset before confirmation', () => {
    assert.equal(countdown(4600, 1000), 'Renueva en 1 h');
    assert.equal(countdown(1001, 1000), 'Renueva en 1 min');
    assert.equal(countdown(1000, 1000), 'Renovación pendiente de confirmar');
    assert.equal(countdown(null), 'Renovación no disponible');
});
test('failure retains old quota with stale state; recovery replaces it', () => {
    const before = {quotas: [{usedPercent: 42}], updatedAt: 123, resetsAvailable: 2};
    const after = mergeResult(before, {status: 'offline', quotas: [], updatedAt: null});
    assert.equal(after.status, 'offline');
    assert.equal(after.updatedAt, 123);
    assert.equal(after.quotas[0].usedPercent, 42);
    assert.equal(after.resetsAvailable, 2);
    const fresh = {status: 'ok', quotas: [{usedPercent: 5}], updatedAt: 456};
    assert.deepEqual(mergeResult(after, fresh), fresh);
});
