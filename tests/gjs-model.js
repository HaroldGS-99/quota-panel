import {usageColor, summaryQuota, countdown, mergeResult} from '../ui-model.js';

function assert(condition, message) {
    if (!condition) throw new Error(message);
}
assert(usageColor(70) === 'warning', 'GJS: yellow threshold');
assert(usageColor(90) === 'critical', 'GJS: red threshold');
assert(usageColor(null) === 'unknown', 'GJS: missing quota');
assert(summaryQuota([{windowMinutes: 300, usedPercent: 25}, {windowMinutes: 10080, usedPercent: 90}]).usedPercent === 25,
    'GJS: five-hour summary');
assert(countdown(1000, 1000) === 'Renovación pendiente de confirmar', 'GJS: reset confirmation');
assert(mergeResult({quotas: [{usedPercent: 80}], updatedAt: 1}, {status: 'offline', quotas: []}).quotas[0].usedPercent === 80,
    'GJS: stale cache');
print('GJS: 6 comprobaciones correctas');
