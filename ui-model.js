export const PROVIDERS = ['codex', 'antigravity', 'opencode'];
export const NAMES = {codex: 'Codex', antigravity: 'Antigravity', opencode: 'OpenCode Go'};

export function usageColor(value, warning = 70, critical = 90) {
    if (value === null || value === undefined || !Number.isFinite(value))
        return 'unknown';
    if (value >= critical)
        return 'critical';
    return value >= warning ? 'warning' : 'normal';
}

export function summaryQuota(quotas = []) {
    const available = quotas.filter(q => Number.isFinite(q.usedPercent) && !q.disabled);
    const short = available.filter(q => q.windowMinutes === 300);
    const candidates = short.length ? short : available;
    return candidates.reduce((chosen, quota) =>
        !chosen || quota.usedPercent > chosen.usedPercent ? quota : chosen, null);
}

export function countdown(reset, now = Date.now() / 1000) {
    if (!Number.isFinite(reset))
        return 'Renovación no disponible';
    const minutes = Math.ceil((reset - now) / 60);
    if (minutes <= 0)
        return 'Renovación pendiente de confirmar';
    const days = Math.floor(minutes / 1440);
    const hours = Math.floor(minutes % 1440 / 60);
    const remainder = minutes % 60;
    const pieces = [];
    if (days) pieces.push(`${days} d`);
    if (hours) pieces.push(`${hours} h`);
    if (remainder || !pieces.length) pieces.push(`${remainder} min`);
    return `Renueva en ${pieces.join(' ')}`;
}

export function ageText(updated, now = Date.now() / 1000) {
    if (!updated)
        return 'Sin datos';
    const minutes = Math.max(0, Math.floor((now - updated) / 60));
    if (minutes < 1) return 'Actualizado ahora';
    if (minutes < 60) return `Último dato hace ${minutes} min`;
    return `Último dato hace ${Math.floor(minutes / 60)} h`;
}

export function mergeResult(previous, incoming) {
    if (incoming.status === 'ok')
        return incoming;
    return {...incoming, quotas: previous?.quotas ?? [], updatedAt: previous?.updatedAt ?? null,
        resetsAvailable: previous?.resetsAvailable ?? null};
}
