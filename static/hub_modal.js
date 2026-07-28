/** Shared progress / result modal — one modal, one dock per site. */
let hubModalBusy = false;
let hubModalMinimized = false;
let hubModalSiteId = null;
let hubModalKind = null;

/** @type {Record<string, object>} in-memory site job/view cache */
const hubSiteViews = {};

const HUB_PROGRESS_KEY = 'okadmin_hub_progress_v2';
const HUB_PROGRESS_KEY_LEGACY = 'okadmin_hub_progress_v1';

window.__hubDeployRunningBySite = window.__hubDeployRunningBySite || {};

function hubEsc(s) {
    const fn = typeof escapeHtmlOps === 'function' ? escapeHtmlOps : (x) => String(x);
    return fn(s);
}

function hubModalEls() {
    return {
        overlay: document.getElementById('hub-results-overlay'),
        modal: document.querySelector('#hub-results-overlay .hub-results-modal'),
        title: document.getElementById('hub-results-title'),
        meta: document.getElementById('hub-results-meta'),
        body: document.getElementById('hub-results-body'),
        close: document.getElementById('hub-results-close'),
        minimize: document.getElementById('hub-results-minimize'),
        docks: document.getElementById('hub-progress-docks'),
    };
}

function hubNormSiteId(siteId) {
    return String(siteId || '').trim() || '_global';
}

/** Site id for the hub page currently on screen (site hub or site-select). */
function hubCurrentSiteId() {
    if (window.__hubPageSiteId) return String(window.__hubPageSiteId).trim();
    const sel = document.getElementById('site-select');
    if (sel?.value) return String(sel.value).trim();
    const m = window.location.pathname.match(/^\/site\/([^/]+)/);
    return m ? decodeURIComponent(m[1]) : '';
}

/** True when deploy/git panel DOM belongs to this site (avoid cross-site bleed). */
function hubIsViewingSite(siteId) {
    const cur = hubCurrentSiteId();
    const sid = hubNormSiteId(siteId);
    return !cur || hubNormSiteId(cur) === sid;
}

function hubLoadAllProgress() {
    try {
        const raw = sessionStorage.getItem(HUB_PROGRESS_KEY);
        if (raw) {
            const data = JSON.parse(raw);
            if (data && typeof data === 'object' && data.sites && typeof data.sites === 'object') {
                return data.sites;
            }
        }
        // Migrate legacy single-job key.
        const legacy = sessionStorage.getItem(HUB_PROGRESS_KEY_LEGACY);
        if (legacy) {
            const job = JSON.parse(legacy);
            if (job?.siteId) {
                const sites = { [job.siteId]: job };
                hubSaveAllProgress(sites);
                sessionStorage.removeItem(HUB_PROGRESS_KEY_LEGACY);
                return sites;
            }
        }
    } catch (_) { /* ignore */ }
    return {};
}

function hubSaveAllProgress(sites) {
    try {
        sessionStorage.setItem(HUB_PROGRESS_KEY, JSON.stringify({ sites, updatedAt: Date.now() }));
    } catch (_) { /* ignore */ }
}

function hubLoadProgress(siteId) {
    if (siteId) return hubLoadAllProgress()[hubNormSiteId(siteId)] || null;
    // Back-compat: first site job (prefer focused modal site).
    const sites = hubLoadAllProgress();
    if (hubModalSiteId && sites[hubModalSiteId]) return sites[hubModalSiteId];
    const keys = Object.keys(sites);
    return keys.length ? sites[keys[0]] : null;
}

function hubPersistProgress(patch, siteId) {
    const sid = hubNormSiteId(siteId || patch?.siteId || hubModalSiteId);
    const sites = hubLoadAllProgress();
    const prev = sites[sid] || hubSiteViews[sid] || {};
    sites[sid] = { ...prev, ...patch, siteId: sid, updatedAt: Date.now() };
    hubSaveAllProgress(sites);
    hubSiteViews[sid] = { ...(hubSiteViews[sid] || {}), ...sites[sid] };
    return sites[sid];
}

function hubClearProgress(siteId) {
    const sid = siteId ? hubNormSiteId(siteId) : hubModalSiteId;
    if (!sid) {
        try {
            sessionStorage.removeItem(HUB_PROGRESS_KEY);
            sessionStorage.removeItem(HUB_PROGRESS_KEY_LEGACY);
        } catch (_) { /* ignore */ }
        return;
    }
    const sites = hubLoadAllProgress();
    delete sites[sid];
    hubSaveAllProgress(sites);
    if (hubSiteViews[sid]) {
        const v = hubSiteViews[sid];
        delete v.jobId;
        delete v.startedAt;
        v.busy = false;
    }
}

function hubSiteHasDeployJob(siteId) {
    const sid = hubNormSiteId(siteId);
    if (window.__hubDeployRunningBySite?.[sid]) return true;
    const job = hubLoadAllProgress()[sid];
    return !!(job && job.kind === 'deploy' && job.jobId && job.state !== 'done' && job.state !== 'failed');
}

function hubModalOwnsSite(siteId) {
    return !!hubModalBusy && hubNormSiteId(siteId) === hubModalSiteId;
}

function hubCanTakeModal(siteId) {
    const sid = hubNormSiteId(siteId);
    if (!hubModalBusy) return true;
    if (hubModalSiteId === sid) return true;
    // Another site owns an open (non-minimized) modal — don't steal.
    if (!hubModalMinimized) return false;
    // Other site is docked — leave their dock; new work uses its own dock only.
    return false;
}

function hubPhaseHtml(phase, running) {
    if (!running) return '';
    const label = phase === 'images' ? '⑥ 이미지' : '① 생성·빌드';
    return `<div class="hub-modal-phases">
        <span class="hub-phase active">${label}</span>
    </div>`;
}

function hubLinesHtml(lines, highlightFirst) {
    const items = Array.isArray(lines) ? lines : [];
    let html = '<ul class="hub-modal-lines">';
    if (!items.length) {
        html += '<li style="color:#666">결과 없음</li>';
    } else {
        items.forEach((line, i) => {
            const cls = highlightFirst && i === 0 && line.startsWith('+ 추가') ? ' class="created-highlight"' : '';
            html += `<li${cls}>${hubEsc(line)}</li>`;
        });
    }
    html += '</ul>';
    return html;
}

function hubLogHtml(full, running, phase) {
    const f = (full || '').trim();
    if (!f) return '';
    const label = running && phase === 'images' ? '상세 로그 (이미지)' : '상세 로그';
    return `<p class="hub-modal-log-label">${hubEsc(label)}</p>`
        + `<pre class="hub-modal-log">${hubEsc(f)}</pre>`;
}

function hubStickLogBottom(el) {
    if (!el) return;
    const pin = () => { el.scrollTop = el.scrollHeight; };
    pin();
    requestAnimationFrame(pin);
}

function hubPinProgressLogs(body) {
    if (!body) return;
    hubStickLogBottom(body.querySelector('.hub-modal-log'));
    hubStickLogBottom(body);
}

function hubProgressBody(view) {
    const colors = { success: '#6a6', running: '#fa0', failed: '#f88', idle: '#888' };
    const c = colors[view.state] || '#fa0';
    const label = view.state === 'success' ? '● 완료' : (view.state === 'failed' ? '● 실패' : '● 진행 중…');
    let html = `<p class="mono hub-progress-pulse" style="color:${c}">${label}</p>`;
    html += hubPhaseHtml(view.phase, view.running);
    html += hubLinesHtml(view.lines, true);
    html += hubLogHtml(view.logFull, view.running, view.phase);
    return html;
}

function hubCacheSiteView(siteId, patch) {
    const sid = hubNormSiteId(siteId);
    hubSiteViews[sid] = { ...(hubSiteViews[sid] || {}), siteId: sid, ...patch };
    return hubSiteViews[sid];
}

function hubEnsureDockEl(siteId) {
    const rail = hubModalEls().docks;
    if (!rail) return null;
    const sid = hubNormSiteId(siteId);
    let el = rail.querySelector(`.hub-progress-dock[data-site-id="${CSS.escape(sid)}"]`);
    if (el) return el;
    el = document.createElement('div');
    el.className = 'hub-progress-dock';
    el.dataset.siteId = sid;
    el.innerHTML = `
        <button type="button" class="hub-dock-main" title="다시 열기">
            <p class="hub-dock-title">진행 중…</p>
            <p class="hub-dock-meta"></p>
        </button>
        <div class="hub-dock-actions">
            <button type="button" class="hub-dock-btn hub-dock-expand" aria-label="다시 열기" title="다시 열기">↑</button>
            <button type="button" class="hub-dock-btn hub-dock-dismiss" aria-label="닫기" title="닫기">×</button>
        </div>`;
    el.querySelector('.hub-dock-main')?.addEventListener('click', () => hubRestoreModal(sid));
    el.querySelector('.hub-dock-expand')?.addEventListener('click', () => hubRestoreModal(sid));
    el.querySelector('.hub-dock-dismiss')?.addEventListener('click', (e) => {
        e.stopPropagation();
        hubDismissDock(sid);
    });
    rail.appendChild(el);
    return el;
}

function hubUpdateSiteDock(siteId, title, meta, state) {
    const view = hubCacheSiteView(siteId, {
        title: title || '진행 중…',
        meta: meta || '',
        state: state || 'running',
    });
    if (view.suppressed && (state === 'running' || !state)) return;
    const el = hubEnsureDockEl(siteId);
    if (!el) return;
    const titleEl = el.querySelector('.hub-dock-title');
    const metaEl = el.querySelector('.hub-dock-meta');
    if (titleEl) titleEl.textContent = view.title || '진행 중…';
    if (metaEl) metaEl.textContent = view.meta || '';
    el.classList.remove('done', 'failed');
    if (state === 'success' || state === 'done') el.classList.add('done');
    else if (state === 'failed') el.classList.add('failed');
    el.classList.add('open');
}

function hubHideSiteDock(siteId) {
    const rail = hubModalEls().docks;
    const sid = hubNormSiteId(siteId);
    const el = rail?.querySelector(`.hub-progress-dock[data-site-id="${CSS.escape(sid)}"]`);
    if (!el) return;
    el.classList.remove('open', 'done', 'failed');
}

function hubShowDock(title, meta, state, siteId) {
    const sid = hubNormSiteId(siteId || hubModalSiteId);
    hubCacheSiteView(sid, { suppressed: false });
    hubUpdateSiteDock(sid, title, meta, state);
}

function hubHideDock(siteId) {
    hubHideSiteDock(siteId || hubModalSiteId);
}

function hubFillModalFromView(view) {
    const { title: titleEl, meta, body } = hubModalEls();
    if (titleEl) titleEl.textContent = view.title || '작업 결과';
    if (meta) meta.textContent = view.meta || '';
    if (body) {
        if (view.bodyHtml != null) body.innerHTML = view.bodyHtml;
        else if (view.running) body.innerHTML = hubProgressBody(view);
    }
}

function hubSnapshotModalBody(siteId) {
    const { title: titleEl, meta, body } = hubModalEls();
    hubCacheSiteView(siteId, {
        title: titleEl?.textContent || '',
        meta: meta?.textContent || '',
        bodyHtml: body?.innerHTML || '',
    });
}

function hubMinimizeProgress() {
    if (!hubModalBusy && !hubModalMinimized) return;
    const sid = hubModalSiteId || '_global';
    const { overlay, title, meta } = hubModalEls();
    hubSnapshotModalBody(sid);
    hubModalMinimized = true;
    overlay?.classList.remove('open');
    const view = hubSiteViews[sid] || {};
    if (!view.suppressed) {
        hubShowDock(
            title?.textContent || view.title || '진행 중…',
            meta?.textContent || view.meta || '',
            hubModalBusy ? 'running' : (view.state || 'done'),
            sid,
        );
    }
    if (hubModalBusy) {
        hubPersistProgress({
            minimized: true,
            title: title?.textContent || view.title,
            meta: meta?.textContent || view.meta,
            kind: hubModalKind || view.kind,
            siteLabel: view.siteLabel,
            jobId: view.jobId,
            startedAt: view.startedAt,
            state: 'running',
        }, sid);
    }
}

function hubRestoreModal(siteId) {
    const sid = hubNormSiteId(siteId || hubModalSiteId);
    const view = hubSiteViews[sid] || hubLoadProgress(sid) || {};
    const { overlay, modal } = hubModalEls();
    if (!overlay) return;

    // If another site's modal is open, minimize it first.
    if (hubModalBusy && hubModalSiteId && hubModalSiteId !== sid && !hubModalMinimized) {
        hubMinimizeProgress();
    }

    hubModalSiteId = sid;
    hubModalKind = view.kind || hubModalKind;
    hubModalMinimized = false;
    hubCacheSiteView(sid, { suppressed: false });
    hubHideSiteDock(sid);
    hubFillModalFromView(view);
    if (view.busy || hubModalBusy && hubModalSiteId === sid) {
        hubModalBusy = !!view.busy || hubModalBusy;
        modal?.classList.toggle('progress', !!hubModalBusy);
    } else {
        hubModalBusy = false;
        modal?.classList.remove('progress');
    }
    // Restoring a finished dock → not busy
    if (view.state === 'done' || view.state === 'failed' || view.state === 'success') {
        hubModalBusy = false;
        modal?.classList.remove('progress');
    }
    overlay.classList.add('open');
    if (!hubModalBusy) hubModalEls().close?.focus();
}

function hubDismissDock(siteId) {
    const sid = hubNormSiteId(siteId || hubModalSiteId);
    const view = hubSiteViews[sid] || {};
    const busy = !!view.busy || (hubModalBusy && hubModalSiteId === sid);
    if (busy) {
        hubCacheSiteView(sid, { suppressed: true });
        hubHideSiteDock(sid);
        return;
    }
    hubHideSiteDock(sid);
    hubClearProgress(sid);
    delete hubSiteViews[sid];
    if (hubModalSiteId === sid) {
        hubModalMinimized = false;
        hubModalEls().overlay?.classList.remove('open');
    }
}

/**
 * @param {string} title
 * @param {string} [detail]
 * @param {{ siteId?: string, siteLabel?: string, kind?: string, takeModal?: boolean }} [opts]
 */
function hubOpenProgress(title, detail, opts = {}) {
    const sid = hubNormSiteId(opts.siteId || hubModalSiteId);
    const kind = opts.kind || 'job';
    const take = opts.takeModal !== false && hubCanTakeModal(sid);

    hubCacheSiteView(sid, {
        title: title || '진행 중…',
        meta: detail || '',
        siteLabel: opts.siteLabel || detail || sid,
        kind,
        busy: true,
        state: 'running',
        suppressed: false,
        running: true,
        bodyHtml: '<p class="mono hub-progress-pulse">● 진행 중…</p>'
            + (detail ? `<p class="mono" style="color:#aaa;margin:8px 0 0;font-size:11px">${hubEsc(detail)}</p>` : ''),
    });

    if (!take) {
        hubUpdateSiteDock(sid, title || '진행 중…', detail || '', 'running');
        if (kind === 'deploy') {
            hubPersistProgress({
                kind, title, meta: detail, siteLabel: opts.siteLabel, state: 'running', minimized: true,
            }, sid);
        }
        return;
    }

    const { overlay, modal, title: titleEl, meta, body } = hubModalEls();
    if (!overlay || !body) return;
    hubModalBusy = true;
    hubModalMinimized = false;
    hubModalSiteId = sid;
    hubModalKind = kind;
    hubHideSiteDock(sid);
    if (titleEl) titleEl.textContent = title || '진행 중…';
    if (meta) meta.textContent = detail || '';
    body.innerHTML = hubSiteViews[sid].bodyHtml;
    modal?.classList.add('progress');
    overlay.classList.add('open');
}

function hubUpdateProgress(view) {
    const sid = hubNormSiteId(view.siteId || hubModalSiteId);
    if (!sid) return;

    const next = hubCacheSiteView(sid, {
        ...view,
        title: view.title || hubSiteViews[sid]?.title,
        meta: view.meta !== undefined ? view.meta : hubSiteViews[sid]?.meta,
        busy: true,
        state: view.state || 'running',
        bodyHtml: undefined,
    });

    // Build body into cache when we own the modal or for later restore.
    const owns = hubModalOwnsSite(sid) || (!hubModalBusy && hubModalSiteId === sid);

    if (hubModalMinimized && hubModalSiteId === sid && !next.suppressed) {
        hubUpdateSiteDock(sid, next.title, next.meta, next.state === 'failed' ? 'failed' : 'running');
    } else if (!hubModalOwnsSite(sid) && hubModalSiteId !== sid) {
        // Background site — dock only.
        if (!next.suppressed) hubUpdateSiteDock(sid, next.title, next.meta, 'running');
    }

    if (!hubModalOwnsSite(sid)) {
        // Still refresh cached body HTML for restore without touching foreign modal.
        const fake = document.createElement('div');
        fake.innerHTML = hubProgressBody(view);
        hubCacheSiteView(sid, { bodyHtml: fake.innerHTML });
        return;
    }

    const { title: titleEl, meta, body } = hubModalEls();
    if (!body || !hubModalBusy) return;
    if (view.title && titleEl) titleEl.textContent = view.title;
    if (view.meta !== undefined && meta) meta.textContent = view.meta;

    const pulse = body.querySelector('.hub-progress-pulse');
    let linesUl = body.querySelector('.hub-modal-lines');
    const full = (view.logFull || '').trim();

    if (pulse && !linesUl) {
        body.innerHTML = hubProgressBody(view);
        hubCacheSiteView(sid, { bodyHtml: body.innerHTML });
        if (!hubModalMinimized) hubPinProgressLogs(body);
        return;
    }

    if (pulse && linesUl) {
        const colors = { success: '#6a6', running: '#fa0', failed: '#f88', idle: '#888' };
        pulse.style.color = colors[view.state] || '#fa0';
        pulse.textContent = view.state === 'success' ? '● 완료' : (view.state === 'failed' ? '● 실패' : '● 진행 중…');

        const phases = body.querySelector('.hub-modal-phases');
        const phaseHtml = hubPhaseHtml(view.phase, view.running);
        if (phaseHtml) {
            if (phases) phases.outerHTML = phaseHtml;
            else pulse.insertAdjacentHTML('afterend', phaseHtml);
        } else if (phases) {
            phases.remove();
        }

        linesUl.outerHTML = hubLinesHtml(view.lines, true);

        if (full) {
            const label = view.running && view.phase === 'images'
                ? '상세 로그 (이미지)'
                : '상세 로그';
            let logLabel = body.querySelector('.hub-modal-log-label');
            if (logLabel) logLabel.textContent = label;
            else body.insertAdjacentHTML('beforeend', `<p class="hub-modal-log-label">${hubEsc(label)}</p>`);
            let pre = body.querySelector('.hub-modal-log');
            if (!pre) {
                body.insertAdjacentHTML('beforeend', `<pre class="hub-modal-log"></pre>`);
                pre = body.querySelector('.hub-modal-log');
            }
            if (pre) {
                pre.textContent = full;
                if (!hubModalMinimized) hubStickLogBottom(pre);
            }
        }
        if (!hubModalMinimized) hubStickLogBottom(body);
        hubCacheSiteView(sid, { bodyHtml: body.innerHTML, title: titleEl?.textContent, meta: meta?.textContent });
        return;
    }

    body.innerHTML = hubProgressBody(view);
    hubCacheSiteView(sid, { bodyHtml: body.innerHTML });
    if (!hubModalMinimized) hubPinProgressLogs(body);
}

function hubFinishProgress(siteId) {
    const sid = hubNormSiteId(siteId || hubModalSiteId);
    hubCacheSiteView(sid, { busy: false, running: false });
    if (hubModalSiteId === sid) {
        hubModalBusy = false;
        hubModalEls().modal?.classList.remove('progress');
    }
}

function hubCloseModal() {
    if (hubModalBusy) {
        hubMinimizeProgress();
        return;
    }
    const sid = hubModalSiteId;
    hubModalMinimized = false;
    if (sid) {
        hubHideSiteDock(sid);
        hubClearProgress(sid);
        delete hubSiteViews[sid];
    }
    hubModalSiteId = null;
    hubModalKind = null;
    hubModalEls().overlay?.classList.remove('open');
}

function hubOpenResult(view) {
    const sid = hubNormSiteId(view.siteId || hubModalSiteId);
    const wasOwner = hubModalOwnsSite(sid) || (!hubModalBusy && hubModalSiteId === sid);
    const wasMinimized = wasOwner && hubModalMinimized;

    let html = '';
    if (view.error) {
        html += `<p class="mono" style="color:#f88;margin:0 0 8px">${hubEsc(view.error)}</p>`;
    }
    html += hubPhaseHtml(view.phase, false);
    html += hubLinesHtml(view.lines, true);
    html += hubLogHtml(view.logFull, false, view.phase);
    if (view.html) html += `<div class="hub-modal-extra">${view.html}</div>`;

    const dockState = view.error || view.state === 'failed' || (view.title || '').includes('실패')
        || (view.title || '').includes('타임아웃')
        ? 'failed'
        : 'done';

    hubCacheSiteView(sid, {
        title: view.title || '작업 결과',
        meta: view.meta || '',
        bodyHtml: html,
        busy: false,
        running: false,
        state: dockState,
        kind: view.kind || hubSiteViews[sid]?.kind,
        suppressed: false,
    });

    if (!view?.keepProgress) hubClearProgress(sid);
    hubFinishProgress(sid);

    // Not the focused modal site — update that site's dock only.
    if (!wasOwner && hubModalSiteId && hubModalSiteId !== sid) {
        hubUpdateSiteDock(sid, view.title || '작업 결과', view.meta || '', dockState);
        return;
    }

    // Take focus if free.
    if (!hubModalBusy || hubModalSiteId === sid || !hubModalSiteId) {
        hubModalSiteId = sid;
        hubModalKind = view.kind || hubModalKind;
    }

    const { overlay, title: titleEl, meta, body } = hubModalEls();
    if (!overlay || !body) return;

    if (wasMinimized || (hubModalMinimized && hubModalSiteId === sid)) {
        hubModalMinimized = true;
        hubModalBusy = false;
        hubShowDock(view.title || '작업 결과', view.meta || '', dockState, sid);
        overlay.classList.remove('open');
        return;
    }

    // If we didn't own the open modal, don't steal — dock only.
    if (hubModalBusy && hubModalSiteId !== sid) {
        hubUpdateSiteDock(sid, view.title || '작업 결과', view.meta || '', dockState);
        return;
    }

    hubModalMinimized = false;
    hubHideSiteDock(sid);
    if (titleEl) titleEl.textContent = view.title || '작업 결과';
    if (meta) meta.textContent = view.meta || '';
    body.innerHTML = html;
    overlay.classList.add('open');
    hubPinProgressLogs(body);
    hubModalEls().close?.focus();
}

function hubSetDeployStatusRow(html, siteId) {
    if (siteId != null && !hubIsViewingSite(siteId)) return;
    const statusRow = document.getElementById('deploy-status-row');
    if (statusRow) statusRow.innerHTML = html;
}

async function hubPollDeployJob(job) {
    const siteId = hubNormSiteId(job.siteId);
    const jobId = job.jobId;
    const label = job.siteLabel || siteId;
    const startedAt = Number(job.startedAt) || Date.now();
    const maxMs = 45 * 60 * 1000;
    window.__hubDeployRunningBySite[siteId] = true;
    // Legacy global used by older UI bits
    window.__hubDeployRunning = Object.values(window.__hubDeployRunningBySite).some(Boolean);

    try {
        while (Date.now() - startedAt < maxMs) {
            await new Promise(r => setTimeout(r, 3000));
            let d;
            try {
                const res = await fetch(
                    `/api/sites/${encodeURIComponent(siteId)}/deploy/status?job_id=${encodeURIComponent(jobId)}`,
                    { credentials: 'same-origin' },
                );
                d = await res.json();
                if (!res.ok || d.error) {
                    const err = d.error || '상태 조회 실패';
                    hubSetDeployStatusRow(
                        '<span class="badge badge-dirty">실패</span>'
                        + `<span class="mono" style="margin-left:8px;color:#f88">${hubEsc(err)}</span>`,
                        siteId,
                    );
                    hubOpenResult({
                        title: '배포 실패', meta: label, error: err, logFull: d.log_tail || '',
                        siteId, kind: 'deploy',
                    });
                    if (typeof showToast === 'function') showToast(`[${label}] 배포 실패: ${err}`);
                    return false;
                }
            } catch (_) {
                continue;
            }

            const msg = d.message || d.state || '';
            if (d.state === 'unknown') {
                hubSetDeployStatusRow(
                    '<span class="badge badge-dirty">확인 필요</span>'
                    + `<span class="mono" style="margin-left:8px">${hubEsc(msg || '서버 재시작으로 추적 끊김 · 로그 확인')}</span>`,
                    siteId,
                );
                hubOpenResult({
                    title: '배포 상태 확인',
                    meta: label,
                    error: msg || '백그라운드 추적 불가 · 아래 로그를 확인하세요',
                    logFull: d.log_tail || '',
                    siteId, kind: 'deploy',
                });
                if (typeof showToast === 'function') showToast(`[${label}] 배포 상태 불명 · 로그 확인`);
                return null;
            }
            if (d.state === 'running') {
                hubSetDeployStatusRow(
                    '<span class="badge badge-dirty">진행 중</span>'
                    + `<span class="mono" style="margin-left:8px">${hubEsc(msg || '배포 진행 중…')}</span>`,
                    siteId,
                );
                const title = '④ 배포 중…';
                const meta = `${label} · 진행 중`;
                hubPersistProgress({
                    kind: 'deploy', title, meta, siteLabel: label, jobId, startedAt,
                    minimized: !(hubModalOwnsSite(siteId) && !hubModalMinimized),
                    state: 'running',
                }, siteId);
                hubUpdateProgress({
                    title, meta, state: 'running', running: true,
                    lines: [msg || 'Cloud Build 진행 중…'],
                    logFull: d.log_tail || '',
                    siteId, kind: 'deploy',
                });
                continue;
            }
            if (d.state === 'success') {
                hubSetDeployStatusRow(
                    '<span class="badge badge-clean">성공</span>'
                    + '<span class="mono" style="margin-left:8px">배포 완료</span>',
                    siteId,
                );
                hubOpenResult({
                    title: '배포 성공', meta: label,
                    lines: ['배포 완료', msg].filter(Boolean),
                    logFull: d.log_tail || '',
                    siteId, kind: 'deploy',
                });
                if (typeof showToast === 'function') showToast(`[${label}] 배포 성공`);
                return true;
            }
            if (d.state === 'failed') {
                const reason = d.error_summary || d.message || '배포 실패';
                hubSetDeployStatusRow(
                    '<span class="badge badge-dirty">실패</span>'
                    + `<span class="mono" style="margin-left:8px;color:#f88">${hubEsc(reason)}</span>`,
                    siteId,
                );
                hubOpenResult({
                    title: '배포 실패', meta: label, error: reason,
                    lines: ['배포 실패', reason],
                    logFull: d.log_tail || '',
                    siteId, kind: 'deploy',
                });
                if (typeof showToast === 'function') showToast(`[${label}] 배포 실패: ${reason}`);
                return false;
            }
        }

        const timeoutMsg = '45분 내 완료 신호 없음';
        hubSetDeployStatusRow(
            '<span class="badge badge-dirty">실패</span>'
            + `<span class="mono" style="margin-left:8px;color:#f88">${timeoutMsg}</span>`,
            siteId,
        );
        hubOpenResult({ title: '배포 타임아웃', meta: label, error: timeoutMsg, siteId, kind: 'deploy' });
        if (typeof showToast === 'function') showToast(`[${label}] 배포 타임아웃 · 로그 확인`);
        return false;
    } finally {
        delete window.__hubDeployRunningBySite[siteId];
        window.__hubDeployRunning = Object.values(window.__hubDeployRunningBySite).some(Boolean);
    }
}

function hubTryResumeProgress() {
    const sites = hubLoadAllProgress();
    Object.values(sites).forEach((job) => {
        if (!job || job.kind !== 'deploy' || !job.siteId || !job.jobId) return;
        const sid = hubNormSiteId(job.siteId);
        if (window.__hubDeployRunningBySite[sid]) return;

        hubCacheSiteView(sid, {
            ...job,
            busy: true,
            state: 'running',
            suppressed: false,
            bodyHtml: '<p class="mono hub-progress-pulse">● 진행 중…</p>'
                + `<p class="mono" style="color:#aaa;margin:8px 0 0;font-size:11px">${hubEsc(job.meta || job.siteLabel || '')}</p>`,
        });
        hubUpdateSiteDock(sid, job.title || '④ 배포 중…', job.meta || job.siteLabel || sid, 'running');

        // Focus first resumed job as minimized owner if modal free.
        if (!hubModalBusy && !hubModalSiteId) {
            hubModalBusy = true;
            hubModalMinimized = true;
            hubModalSiteId = sid;
            hubModalKind = 'deploy';
            const { modal, title: titleEl, meta, body, overlay } = hubModalEls();
            if (titleEl) titleEl.textContent = job.title || '④ 배포 중…';
            if (meta) meta.textContent = job.meta || job.siteLabel || sid;
            if (body) body.innerHTML = hubSiteViews[sid].bodyHtml;
            modal?.classList.add('progress');
            overlay?.classList.remove('open');
        }

        hubPollDeployJob(job).finally(() => {
            if (typeof loadSiteWorkflow === 'function' && hubIsViewingSite(sid)) {
                try { loadSiteWorkflow(sid); } catch (_) { /* optional */ }
            }
        });
    });
}

function pipelineStatusView(summary, logTail, opts = {}) {
    const phase = opts.phase || null;
    const running = !!opts.running;
    const title = summary?.title || '—';
    let state = 'idle';
    if (title === '완료') state = 'success';
    else if (title === '실패') state = 'failed';
    else if (running) state = 'running';

    const lines = [];
    if (summary?.created_labels?.length) {
        lines.push(`+ 추가 ${summary.created_labels.length}건: ${summary.created_labels.join(', ')}`);
    }
    lines.push(...(summary?.lines?.length ? summary.lines : (running ? [] : ['결과 없음'])));

    const fullText = logTail || '';

    let modalTitle = title;
    if (running && phase === 'images') modalTitle = '⑥ 이미지 처리 중';
    else if (running) modalTitle = '① 생성·빌드 중';
    else if (title === '완료') modalTitle = '콘텐츠 생성 완료';
    else if (title === '실패') modalTitle = '콘텐츠 생성 실패';

    return {
        title: modalTitle,
        meta: opts.siteLabel || '',
        lines,
        logFull: fullText,
        state,
        phase,
        running,
        siteId: opts.siteId,
        kind: 'content',
    };
}

function initHubModal() {
    const els = hubModalEls();
    els.close?.addEventListener('click', hubCloseModal);
    els.minimize?.addEventListener('click', hubMinimizeProgress);
    document.getElementById('hub-results-overlay')?.addEventListener('click', e => {
        if (e.target?.id !== 'hub-results-overlay') return;
        if (hubModalBusy) hubMinimizeProgress();
        else hubCloseModal();
    });
    document.addEventListener('keydown', e => {
        if (e.key !== 'Escape') return;
        const overlay = document.getElementById('hub-results-overlay');
        if (hubModalBusy && overlay?.classList.contains('open')) {
            hubMinimizeProgress();
            return;
        }
        if (hubModalBusy) return;
        if (overlay?.classList.contains('open')) hubCloseModal();
    });
    hubTryResumeProgress();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHubModal);
} else {
    initHubModal();
}
