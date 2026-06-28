/** Site hub — workflow strip navigation, action bars */
const ACTIVE_SITE_KEY = 'okadmin_active_site_v1';
const HUB_SECTIONS = ['content', 'deploy', 'metrics', 'seo'];

function normalizeSection(raw) {
    const s = (raw || 'content').trim().toLowerCase();
    if (s === 'work') return 'content';
    return HUB_SECTIONS.includes(s) ? s : 'content';
}

function initSiteHub(siteId, initialSection, siteColor) {
    try { localStorage.setItem(ACTIVE_SITE_KEY, siteId); } catch (_) {}

    const panels = document.querySelectorAll('.hub-panel');
    const wfSteps = document.querySelectorAll('.wf-step');
    let currentSection = normalizeSection(initialSection);

    function switchSection(name) {
        const section = normalizeSection(name);
        currentSection = section;
        panels.forEach(p => p.classList.toggle('active', p.id === 'panel-' + section));
        wfSteps.forEach(s => s.classList.toggle('active', s.dataset.section === section));
        const url = new URL(window.location.href);
        url.searchParams.set('section', section);
        url.searchParams.delete('tab');
        history.replaceState(null, '', url.pathname + '?' + url.searchParams.toString());
        if (window.__hubSite) {
            const pipe = typeof pipelineForSite === 'function' ? pipelineForSite(siteId) : null;
            updateWorkflowStrip(window.__hubSite, window.__hubLogs || {}, pipe);
        }
        resizeHubIframes();
    }

    wfSteps.forEach(s => s.addEventListener('click', () => switchSection(s.dataset.section)));

    const sel = document.getElementById('site-select');
    if (sel) {
        sel.addEventListener('change', () => {
            const id = sel.value;
            try { localStorage.setItem(ACTIVE_SITE_KEY, id); } catch (_) {}
            const section = normalizeSection(new URLSearchParams(location.search).get('section')
                || new URLSearchParams(location.search).get('tab'));
            window.location.href = '/site/' + encodeURIComponent(id) + '?section=' + section;
        });
    }

    switchSection(currentSection);

    wireHubEmbedIframes();
    (async () => {
        if (typeof refreshBacklog === 'function') {
            await refreshBacklog(siteId, { silent: true });
        }
        await loadPipelines();
        renderContentBar(siteId);
        loadSiteWorkflow(siteId);
    })();
}

function wireHubEmbedIframes() {
    const metrics = document.getElementById('iframe-metrics');
    const seo = document.getElementById('iframe-seo');
    [metrics, seo].forEach(iframe => {
        if (!iframe) return;
        iframe.addEventListener('load', () => resizeHubIframe(iframe));
    });
    window.addEventListener('message', (e) => {
        if (e.data?.type === 'okadmin-embed-resize') {
            [metrics, seo].forEach(iframe => {
                if (iframe && e.source === iframe.contentWindow) {
                    setHubIframeHeight(iframe, e.data.height);
                }
            });
            return;
        }
        if (e.data?.type === 'okadmin-hub-refresh') {
            const siteId = document.getElementById('site-select')?.value;
            if (siteId && (!e.data.site_id || e.data.site_id === siteId)) {
                loadSiteWorkflow(siteId);
            }
        }
    });
}

function setHubIframeHeight(iframe, height) {
    const h = Math.max(320, Number(height) || 0);
    iframe.style.height = h + 'px';
}

function resizeHubIframe(iframe) {
    if (!iframe) return;
    try {
        const doc = iframe.contentDocument;
        if (doc) {
            const h = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight);
            setHubIframeHeight(iframe, h);
        }
    } catch (_) {}
}

function resizeHubIframes() {
    resizeHubIframe(document.getElementById('iframe-metrics'));
    resizeHubIframe(document.getElementById('iframe-seo'));
}

function wfStepClass(status) {
    if (status === 'overdue' || status === 'never') return 'wf-alert';
    if (status === 'today' || status === 'soon') return 'wf-warn';
    if (status === 'ok') return 'wf-ok';
    return '';
}

async function loadSiteWorkflow(siteId) {
    const [sitesRes, logsRes, pipesRes] = await Promise.all([
        fetch('/api/sites'),
        fetch('/api/dashboard/logs'),
        fetch('/api/content/pipelines'),
    ]);
    let sites = [], logData = {}, pipelines = [];
    try { sites = await sitesRes.json(); } catch (_) {}
    try { logData = await logsRes.json(); } catch (_) {}
    try { pipelines = await pipesRes.json(); } catch (_) {}

    const site = sites.find(s => s.id === siteId);
    const logs = (logData.sites || {})[siteId] || {};
    const pipe = pipelines.find(p => p.site_id === siteId);

    window.__hubSite = site;
    window.__hubLogs = logs;
    renderDeployPanel(site, logs);
    updateWorkflowStrip(site, logs, pipe);
}

function renderContentBar(siteId) {
    const hint = document.getElementById('content-hint');
    const actions = document.getElementById('content-actions');
    if (!hint || !actions) return;

    const p = typeof pipelineForSite === 'function' ? pipelineForSite(siteId) : null;
    const snap = typeof pipelineBacklogSnap === 'function' ? pipelineBacklogSnap(p) : p?.backlog;
    const remain = backlogSummaryText(p, siteId);
    const exp = snap?.csv_expand || {};
    const expandAvail = (exp.items_expandable || 0) + (exp.guides_expandable || 0);
    const nextLine = typeof nextRunText === 'function' ? nextRunText(snap) : '';

    let hintText = remain === '없음'
        ? '백로그 없음 · CSV 추가로 토픽을 채울 수 있음'
        : `남은 건수: ${remain}`;
    if (nextLine) hintText += ` · ${nextLine}`;
    if (expandAvail > 0) hintText += ` · CSV 추가 가능 ${expandAvail}건`;
    const csv = snap?.csv;
    if (csv && (csv.items != null || csv.guides != null)) {
        const csvBits = [];
        if (csv.items != null) csvBits.push(`CSV 아이템 ${csv.items}`);
        if (csv.guides != null) csvBits.push(`CSV 가이드 ${csv.guides}`);
        if (csvBits.length) hintText += ` · ${csvBits.join(' · ')}`;
    }
    if (snap?.computed_at) hintText += ` · ${snap.computed_at}`;
    hint.textContent = hintText;

    const label = escHub(p?.label || siteId);
    const running = p?.running;
    const runLabel = running
        ? (p.phase === 'deploy' ? '② 배포 중…' : '① 생성 중…')
        : '콘텐츠 생성';
    const runDisabled = !(p?.available && !running);
    const csvTitle = expandAvail
        ? `CSV에 ${expandAvail}건 추가 가능 (시드 토픽)`
        : '추가할 시드 없음 — 이미 모두 등록됨';

    let html = `<button type="button" class="btn btn-ghost" onclick="refreshBacklog('${escHub(siteId)}')" ${running ? 'disabled' : ''}>건수 새로고침</button>`;
    html += `<button type="button" class="btn btn-ghost" onclick="expandCsv('${escHub(siteId)}')" ${running || !expandAvail ? 'disabled' : ''} title="${escHub(csvTitle)}">CSV 추가${expandAvail ? ` (${expandAvail})` : ''}</button>`;
    html += `<button type="button" class="btn" id="hub-run-pipeline" ${runDisabled ? 'disabled' : ''}
        onclick="runPipeline('${escHub(siteId)}', '${label}')">${escHub(runLabel)}</button>`;
    actions.innerHTML = html;

    if (running) activePipelineSite = siteId;
}

function backlogSummaryText(p, siteId) {
    if (p?.backlog?.summary) return p.backlog.summary;
    if (typeof remainingText === 'function') return remainingText(p || {});
    return '—';
}

function renderDeployPanel(site, logs) {
    const gitEl = document.getElementById('deploy-git');
    const actionsEl = document.getElementById('deploy-actions');
    const metaEl = document.getElementById('deploy-recent-meta');
    const listEl = document.getElementById('deploy-log-list');
    if (!gitEl || !actionsEl) return;

    if (!site) {
        gitEl.innerHTML = '<span class="mono">—</span>';
        actionsEl.innerHTML = '';
        return;
    }

    const git = site.git_summary;
    if (site.git === false) {
        gitEl.innerHTML = '<span class="mono">Git 없음</span>';
        actionsEl.innerHTML = '';
    } else if (!git || git.error) {
        gitEl.innerHTML = `<span class="mono" style="color:#a66">${escHub(git?.error || 'Git 없음')}</span>`;
        actionsEl.innerHTML = '';
    } else {
        const badge = git.dirty
            ? '<span class="badge badge-dirty">dirty</span>'
            : '<span class="badge badge-clean">clean</span>';
        gitEl.innerHTML = `${badge}<span class="mono">${escHub(git.branch || 'main')}</span>`;
        let btns = `<button type="button" class="btn" id="hub-git-push">Push</button>`;
        if (site.has_deploy) {
            btns += `<button type="button" class="btn btn-ghost" id="hub-git-deploy">Deploy</button>`;
        }
        actionsEl.innerHTML = btns;

        const pushBtn = document.getElementById('hub-git-push');
        if (pushBtn) {
            pushBtn.onclick = async () => {
                pushBtn.disabled = true;
                const res = await fetch(`/api/sites/${encodeURIComponent(site.id)}/push`, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{}',
                });
                const d = await res.json();
                showToast(d.message || d.error || (res.ok ? 'Push 완료' : '실패'));
                pushBtn.disabled = false;
                loadSiteWorkflow(site.id);
            };
        }
        const depBtn = document.getElementById('hub-git-deploy');
        if (depBtn) {
            depBtn.onclick = async () => {
                depBtn.disabled = true;
                const res = await fetch(`/api/sites/${encodeURIComponent(site.id)}/deploy`, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{}',
                });
                const d = await res.json();
                if (d.job_id) {
                    showToast('Deploy 시작');
                    pollDeployStatus(site.id, d.job_id, null, () => {
                        depBtn.disabled = false;
                        loadSiteWorkflow(site.id);
                    });
                } else {
                    showToast(d.error || d.message || 'Deploy 실패');
                    depBtn.disabled = false;
                }
            };
        }
    }

    const deps = logs.deploy || [];
    const lastContent = logs.last_content_added_at;
    if (metaEl) {
        const parts = [];
        if (lastContent) {
            const mark = logs.last_content_added_ok === true ? '성공' : (logs.last_content_added_ok === false ? '실패' : '');
            parts.push(`콘텐츠 추가 ${lastContent}${mark ? ' ' + mark : ''}`);
        }
        if (deps[0]) {
            const st = deps[0].state === 'success' ? '성공' : (deps[0].state === 'failed' ? '실패' : deps[0].state);
            parts.push(`배포 ${deps[0].mtime} ${st}`);
        }
        metaEl.textContent = parts.length ? parts.join(' · ') : '최근 배포·콘텐츠 기록 없음';
    }

    if (listEl) {
        const rows = [];
        deps.forEach(d => {
            const st = d.state === 'success' ? '성공' : (d.state === 'failed' ? '실패' : d.state);
            rows.push(`<li>${escHub(d.mtime)} · ${escHub(st)}</li>`);
        });
        if (lastContent) {
            const mark = logs.last_content_added_ok === true ? '성공' : (logs.last_content_added_ok === false ? '실패' : '');
            const line = `콘텐츠 ${escHub(lastContent)}${mark ? ' ' + escHub(mark) : ''}`;
            if (!rows.some(r => r.includes('콘텐츠'))) rows.unshift(`<li>${line}</li>`);
        }
        listEl.innerHTML = rows.length ? rows.join('') : '<li style="color:#666">기록 없음</li>';
    }
}

function updateWorkflowStrip(site, logs, pipe) {
    const current = normalizeSection(new URLSearchParams(location.search).get('section'));
    const remain = typeof remainingText === 'function' ? remainingText(pipe || {}) : '—';
    const contentSt = (logs.content_schedule && logs.content_schedule.status) || 'never';
    const gscSt = (logs.gsc_schedule && logs.gsc_schedule.status) || 'never';

    const cLabel = document.getElementById('wf-content-label');
    const cMeta = document.getElementById('wf-content-meta');
    if (cLabel) cLabel.textContent = remain === '없음' ? '백로그 없음' : remain;
    if (cMeta) cMeta.textContent = logs.content_due_label || '7일 주기';
    const cStep = document.getElementById('wf-content');
    if (cStep) {
        cStep.className = 'wf-step ' + wfStepClass(contentSt) + (current === 'content' ? ' active' : '');
    }

    const git = site?.git_summary;
    const dLabel = document.getElementById('wf-deploy-label');
    const dMeta = document.getElementById('wf-deploy-meta');
    if (dLabel) dLabel.textContent = git?.dirty ? 'Push 필요' : (git ? 'clean' : '—');
    if (dMeta) dMeta.textContent = logs.last_content_added_at ? `최근 ${logs.last_content_added_at}` : '배포 기록 없음';
    const dStep = document.getElementById('wf-deploy');
    if (dStep) {
        dStep.className = 'wf-step ' + (git?.dirty ? 'wf-warn' : '') + (current === 'deploy' ? ' active' : '');
    }

    const mStep = document.getElementById('wf-metrics');
    const mMeta = document.getElementById('wf-metrics-meta');
    if (mMeta) mMeta.textContent = 'GA4 · GSC 차트';
    if (mStep) mStep.className = 'wf-step' + (current === 'metrics' ? ' active' : '');

    const sLabel = document.getElementById('wf-seo-label');
    const sMeta = document.getElementById('wf-seo-meta');
    if (sLabel) sLabel.textContent = logs.gsc_due_label || 'SEO';
    if (sMeta) sMeta.textContent = logs.last_gsc_response_at ? `최근 ${logs.last_gsc_response_at}` : '실행 기록 없음';
    const sStep = document.getElementById('wf-seo');
    if (sStep) {
        sStep.className = 'wf-step ' + wfStepClass(gscSt) + (current === 'seo' ? ' active' : '');
    }
}

function escHub(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

window.rerenderDashboard = function rerenderSiteWork() {
    const siteId = document.getElementById('site-select')?.value;
    if (siteId) {
        renderContentBar(siteId);
        loadSiteWorkflow(siteId);
    }
};
