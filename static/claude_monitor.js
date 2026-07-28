/** Claude Code subscription usage — shared Hub banner + dashboard cards. */
(function (global) {
    'use strict';

    const API = '/api/content/claude-usage';
    const POLL_MS = 300000;
    const WINDOW_PRIORITY = ['five_hour', 'seven_day'];
    const HOME_WINDOW_KEYS = ['five_hour', 'seven_day'];
    const LEVEL_RANK = { ok: 0, warn: 1, danger: 2, over: 3 };

    let lastData = null;
    let pollTimer = null;

    function esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/"/g, '&quot;');
    }

    function windows(data) {
        return Array.isArray(data && data.windows) ? data.windows : [];
    }

    function byKey(data) {
        const out = {};
        windows(data).forEach((w) => {
            if (w && w.key) out[w.key] = w;
        });
        return out;
    }

    function primaryWindow(data) {
        const map = byKey(data);
        for (let i = 0; i < WINDOW_PRIORITY.length; i++) {
            if (map[WINDOW_PRIORITY[i]]) return map[WINDOW_PRIORITY[i]];
        }
        const ws = windows(data);
        return ws.length ? ws[0] : null;
    }

    function worstLevel(data) {
        if (data && data.worst_level) return data.worst_level;
        let worst = 'ok';
        windows(data).forEach((w) => {
            const lv = w.level || 'ok';
            if ((LEVEL_RANK[lv] || 0) > (LEVEL_RANK[worst] || 0)) worst = lv;
        });
        return worst;
    }

    function pipelineOk(data) {
        if (!data) return true;
        if (typeof data.pipeline_ok === 'boolean') return data.pipeline_ok;
        const gate = byKey(data).five_hour || primaryWindow(data);
        if (!gate) return worstLevel(data) !== 'danger' && worstLevel(data) !== 'over';
        if (gate.percent_stale || gate.expired) return true;
        const lv = gate.level || 'ok';
        const pct = Number(gate.percent) || 0;
        return lv !== 'danger' && lv !== 'over' && pct < 85;
    }

    function headline(data) {
        if (!data) return '';
        if (data.headline) return String(data.headline);
        if (data.error) return String(data.error);
        const p = primaryWindow(data);
        if (!p) return data.note ? String(data.note) : '';
        if (p.percent_stale || p.expired) {
            return `${p.label || p.key} 리셋됨 — 사용량 재조회 필요`;
        }
        const pct = Number(p.percent) || 0;
        let text = `${p.label || p.key} ${pct.toFixed(0)}%`;
        if (p.resets_in) text += ` · 리셋 ${p.resets_in} 후`;
        else if (p.resets_local) text += ` · 리셋 ${p.resets_local}`;
        return text;
    }

    function bannerLevel(data) {
        const lv = worstLevel(data);
        if (!pipelineOk(data)) return 'danger';
        return lv;
    }

    function renderBanner(el, data) {
        if (!el) return;
        if (!data || !windows(data).length) {
            const msg = (data && (data.error || data.note)) || '';
            if (!msg) {
                el.hidden = true;
                el.innerHTML = '';
                return;
            }
            el.hidden = false;
            el.className = 'hub-claude-banner level-warn';
            el.innerHTML = `<span class="hub-claude-banner-label">Claude</span><span>${esc(msg)}</span>`;
            return;
        }
        const lv = bannerLevel(data);
        const text = headline(data);
        if (lv === 'ok' && pipelineOk(data)) {
            el.hidden = true;
            el.innerHTML = '';
            return;
        }
        el.hidden = false;
        el.className = `hub-claude-banner level-${lv}`;
        const hint = pipelineOk(data)
            ? '대량 생성 시 한도 주의'
            : '콘텐츠 생성 일시 중단 · 리셋 후 재시도';
        el.innerHTML =
            `<span class="hub-claude-banner-label">Claude</span>`
            + `<span class="hub-claude-banner-text">${esc(text)}</span>`
            + `<span class="hub-claude-banner-hint">${esc(hint)}</span>`;
    }

    function renderCards(panel, data, opts) {
        if (!panel || !data) return;
        const options = opts || {};
        const allow = options.keys || HOME_WINDOW_KEYS;
        const ws = windows(data).filter((w) => w && allow.includes(w.key));
        const plan = (data.subscription_type || 'Claude').toString();
        if (!ws.length) {
            const msg = data.error || 'Claude 사용량 없음';
            panel.innerHTML = `<p class="claude-usage-meta"><span class="claude-usage-meta-text">${esc(msg)}</span></p>`;
            panel.hidden = false;
            return;
        }
        const cards = ws.map((w) => {
            const pct = Math.min(100, Number(w.percent) || 0);
            const level = w.level || 'ok';
            const remain = w.remaining_percent != null ? w.remaining_percent : (100 - pct);
            const reset = w.resets_local
                ? `리셋 ${esc(w.resets_local)}${w.resets_in ? ` · ${esc(w.resets_in)} 후` : ''}`
                : '리셋 시각 없음';
            const staleHint = w.percent_stale || w.expired
                ? `<p class="ai-spend-today stale-hint">${esc(w.stale_hint || '리셋됨 — %는 캐시(재조회 필요)')}</p>`
                : '';
            const pctLabel = (w.percent_stale || w.expired) ? `캐시 ${pct.toFixed(0)}%` : `${pct.toFixed(0)}% 사용`;
            return `<div class="ai-spend-card ${level}">
                <div class="ai-spend-head">
                    <span class="ai-spend-title claude">${esc(w.label)} · ${esc(plan)}</span>
                    <span class="ai-spend-nums">${esc(pctLabel)}</span>
                </div>
                <div class="ai-spend-bar ${level}"><span style="width:${pct}%"></span></div>
                <p class="ai-spend-sub">남음 ${Number(remain).toFixed(0)}%</p>
                <p class="ai-spend-today">${reset}</p>
                ${staleHint}
            </div>`;
        }).join('');
        panel.innerHTML = cards;
        panel.hidden = false;
    }

    function applyState(data) {
        lastData = data;
        global.__claudeUsage = data;
        global.__claudePipelineOk = pipelineOk(data);
        renderBanner(document.getElementById('claude-hub-banner'), data);
        renderBanner(document.getElementById('claude-dash-banner'), data);
        const panel = document.getElementById('claude-usage-panel');
        if (panel) renderCards(panel, data, { keys: HOME_WINDOW_KEYS });
        if (typeof global.onClaudeUsageUpdated === 'function') {
            global.onClaudeUsageUpdated(data);
        }
    }

    async function fetchUsage(force) {
        const q = force ? '?force=1' : '';
        const res = await fetch(API + q);
        if (!res.ok) return null;
        return res.json();
    }

    async function load(force) {
        try {
            const data = await fetchUsage(force);
            if (data) applyState(data);
            return data;
        } catch (_) {
            return null;
        }
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(() => load(false), POLL_MS);
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') load(false);
        });
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    global.ClaudeMonitor = {
        load,
        fetchUsage,
        applyState,
        startPolling,
        stopPolling,
        pipelineOk,
        headline,
        worstLevel,
        bannerLevel,
        renderBanner,
        renderCards,
        getLast: () => lastData,
    };
})(typeof window !== 'undefined' ? window : globalThis);
