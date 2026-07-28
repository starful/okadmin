/** Site hub — workflow strip navigation */
const ACTIVE_SITE_KEY = 'okadmin_active_site_v1';
const HUB_SECTIONS = ['content', 'seo', 'git', 'deploy', 'metrics', 'images'];

function normalizeSection(raw) {
    const s = (raw || 'content').trim().toLowerCase();
    if (s === 'work') return 'content';
    if (s === 'instagram') return 'content';
    return HUB_SECTIONS.includes(s) ? s : 'content';
}

function initSiteHub(siteId, initialSection, siteColor) {
    window.__hubPageSiteId = siteId;
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
        if (section === 'git') {
            refreshGitPanel(siteId);
            refreshGitHubShip(siteId);
        }
        ensureHubIframeLoaded(section);
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
    wireGitPanel(siteId);
    wireDeployPanel(siteId);

    if (typeof ClaudeMonitor !== 'undefined') {
        window.onClaudeUsageUpdated = function () {
            const sid = document.getElementById('site-select')?.value;
            if (sid && typeof renderContentBar === 'function') renderContentBar(sid);
        };
        ClaudeMonitor.load(false).then(() => ClaudeMonitor.startPolling());
    }

    (async () => {
        try {
            if (typeof refreshBacklog === 'function') {
                await refreshBacklog(siteId, { silent: true });
            }
            await loadPipelines();
        } catch (_) {}
        renderContentBar(siteId);
        loadSiteWorkflow(siteId);
    })();
}

function hubIframeIds() {
    return ['iframe-metrics', 'iframe-seo', 'iframe-images'];
}

function wireHubEmbedIframes() {
    hubIframeIds().forEach(id => {
        const iframe = document.getElementById(id);
        if (!iframe) return;
        iframe.addEventListener('load', () => resizeHubIframe(iframe));
    });
    window.addEventListener('message', (e) => {
        if (e.data?.type === 'okadmin-embed-resize') {
            hubIframeIds().forEach(id => {
                const iframe = document.getElementById(id);
                if (iframe && e.source === iframe.contentWindow) {
                    setHubIframeHeight(iframe, e.data.height);
                }
            });
            return;
        }
        if (e.data?.type === 'okadmin-embed-toast' && e.data.message) {
            const fromHub = hubIframeIds().some(id => {
                const iframe = document.getElementById(id);
                return iframe && e.source === iframe.contentWindow;
            });
            if (fromHub && typeof showToast === 'function') showToast(e.data.message);
            return;
        }
        if (e.data?.type === 'okadmin-hub-refresh') {
            const siteId = document.getElementById('site-select')?.value;
            if (siteId && (!e.data.site_id || e.data.site_id === siteId)) {
                loadSiteWorkflow(siteId);
                if (normalizeSection(new URLSearchParams(location.search).get('section')) === 'git') {
                    refreshGitPanel(siteId);
                }
            }
        }
    });
}

function ensureHubIframeLoaded(section) {
    const idMap = {
        metrics: 'iframe-metrics',
        seo: 'iframe-seo',
        images: 'iframe-images',
    };
    const iframe = document.getElementById(idMap[section]);
    if (!iframe) return;
    const wanted = iframe.getAttribute('data-src');
    if (!wanted) return;
    if (iframe.dataset.hubLoaded === '1') return;
    iframe.dataset.hubLoaded = '1';
    iframe.src = wanted;
}

function setHubIframeHeight(iframe, height) {
    if (!iframe) return;
    // GCS images embed uses fixed CSS height; growing it puts modals off-screen.
    if (iframe.id === 'iframe-images') return;
    const h = Math.max(320, Number(height) || 0);
    const prev = parseInt(iframe.style.height, 10) || 0;
    if (Math.abs(prev - h) < 4) return;
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
    hubIframeIds().forEach(id => resizeHubIframe(document.getElementById(id)));
}

function wfStepClass(status) {
    if (status === 'overdue' || status === 'never') return 'wf-alert';
    if (status === 'today' || status === 'soon') return 'wf-warn';
    if (status === 'ok') return 'wf-ok';
    return '';
}

async function loadSiteWorkflow(siteId) {
    const requested = siteId;
    const [sitesRes, logsRes, pipesRes] = await Promise.all([
        fetch('/api/sites'),
        fetch('/api/dashboard/logs'),
        fetch('/api/content/pipelines'),
    ]);
    let sites = [], logData = {}, pipelines = [];
    try { sites = await sitesRes.json(); } catch (_) {}
    try { logData = await logsRes.json(); } catch (_) {}
    try { pipelines = await pipesRes.json(); } catch (_) {}
    if (Array.isArray(pipelines)) window.__pipelines = pipelines;

    if (typeof hubIsViewingSite === 'function' && !hubIsViewingSite(requested)) return;

    const site = sites.find(s => s.id === requested);
    const logs = (logData.sites || {})[requested] || {};
    const pipe = pipelines.find(p => p.site_id === requested);

    window.__hubSite = site;
    window.__hubLogs = logs;
    renderDeployActions(site, logs);
    updateWorkflowStrip(site, logs, pipe);
}

function renderContentBar(siteId) {
    const hint = document.getElementById('content-hint');
    const actions = document.getElementById('content-actions');
    if (!hint || !actions) return;

    if (typeof saveAqCountsFromDom === 'function') saveAqCountsFromDom(siteId);

    const p = typeof pipelineForSite === 'function' ? pipelineForSite(siteId) : null;
    const snap = typeof pipelineBacklogSnap === 'function' ? pipelineBacklogSnap(p) : p?.backlog;
    const exp = snap?.csv_expand || {};
    const expandAvail = (exp.items_expandable || 0) + (exp.guides_expandable || 0);

    if (typeof generatableHtml === 'function') {
        hint.innerHTML = generatableHtml(snap, siteId);
        hint.className = 'hub-load-hint generatable-summary';
    } else {
        hint.textContent = `MD 대기: ${typeof mdPendingText === 'function' ? mdPendingText(snap, siteId) : '—'}`;
        hint.className = 'hub-load-hint';
    }

    const label = escHub(p?.label || siteId);
    const running = p?.running;
    const claudeBlocked = typeof ClaudeMonitor !== 'undefined' && !ClaudeMonitor.pipelineOk(ClaudeMonitor.getLast());
    const runLabel = running
        ? '① 생성 중…'
        : (claudeBlocked ? 'Claude 한도' : (siteId === 'krcare' ? 'TourAPI 갱신' : '콘텐츠 생성'));
    const runDisabled = !(p?.available && !running) || claudeBlocked;
    const runTitle = claudeBlocked
        ? (typeof ClaudeMonitor !== 'undefined' ? ClaudeMonitor.headline(ClaudeMonitor.getLast()) : 'Claude 한도')
        : '';
    let html = `<button type="button" class="btn btn-ghost" onclick="refreshBacklog('${escHub(siteId)}')" ${running ? 'disabled' : ''}>건수 새로고침</button>`;
    const canExpand = typeof supportsTopicExpand !== 'function' || supportsTopicExpand(siteId);
    if (canExpand && typeof isAiQueueSite === 'function' && isAiQueueSite(siteId)) {
        const contentLabel = typeof aiQueueContentLabel === 'function' ? aiQueueContentLabel(siteId) : '아이템';
        html += aiQueueInputs(siteId, snap, running);
        html += `<button type="button" class="btn btn-ghost" onclick="expandCsv('${escHub(siteId)}')" ${running ? 'disabled' : ''} title="AI가 ${escHub(contentLabel)}·가이드 주제를 목록에 추가">목록 추가</button>`;
        if (siteId === 'jpcampus' && typeof openStayPublishPanel === 'function') {
            html += `<button type="button" class="btn btn-ghost" onclick="openStayPublishPanel()" ${running ? 'disabled' : ''} title="숙소 카탈로그에서 선택 발행">숙소 발행</button>`;
        }
    } else if (canExpand) {
        const csvTitle = expandAvail
            ? `CSV에 ${expandAvail}건 추가 가능 (시드 토픽)`
            : '주간 시드 토픽 추가 (이미 있으면 스킵)';
        html += `<button type="button" class="btn btn-ghost" onclick="expandCsv('${escHub(siteId)}')" ${running ? 'disabled' : ''} title="${escHub(csvTitle)}">CSV 추가${expandAvail ? ` (${expandAvail})` : ''}</button>`;
    }
    html += `<button type="button" class="btn" id="hub-run-pipeline" ${runDisabled ? 'disabled' : ''}
        ${runTitle ? `title="${escHub(runTitle)}"` : ''}
        onclick="runPipeline('${escHub(siteId)}', '${label}')">${escHub(runLabel)}</button>`;
    actions.innerHTML = html;
    if (typeof bindAqSteppers === 'function') bindAqSteppers(actions);

    if (running) activePipelineSite = siteId;
}

function wireGitPanel(siteId) {
    const refresh = document.getElementById('git-btn-refresh');
    if (refresh) refresh.onclick = () => {
        refreshGitPanel(siteId);
        refreshGitHubShip(siteId);
    };
    wireGitHubShip(siteId);
    wireShipReviewModal(siteId);
}

async function refreshGitHubShip(siteId) {
    const meta = document.getElementById('github-ship-meta');
    const prLine = document.getElementById('github-pr-line');
    if (!meta) return;
    try {
        const [cfgRes, prRes] = await Promise.all([
            fetch(`/api/sites/${encodeURIComponent(siteId)}/github`),
            fetch(`/api/sites/${encodeURIComponent(siteId)}/github/pr`),
        ]);
        const cfg = await cfgRes.json();
        const prData = await prRes.json();
        window.__hubGithubCfg = cfg;
        window.__hubGithubPr = prData;
        if (!cfg.gh?.logged_in) {
            const err = cfg.gh?.error || 'gh not ready';
            const hint = err.toLowerCase().includes('not found')
                ? '<code>brew install gh</code> then <code>gh auth login</code>'
                : '<code>gh auth login</code>';
            meta.innerHTML = `<span style="color:#c90">${escHub(err)}</span> · ${hint}`;
            if (prLine) prLine.textContent = cfg.gh?.detail || '—';
            return;
        }
        const repo = cfg.repo || '?';
        const branch = cfg.branch || '?';
        const onMain = cfg.on_production_branch;
        meta.innerHTML = `<span class="mono">${escHub(repo)}</span> · branch <strong>${escHub(branch)}</strong>`
            + (onMain ? ' <span class="badge badge-clean">main</span>' : ' <span class="badge badge-dirty">feature</span>');
        const pr = prData.pr;
        if (prLine) {
            if (pr && pr.url) {
                const merge = pr.mergeable ? 'mergeable' : (pr.mergeable === false ? 'conflict' : '');
                prLine.innerHTML = `<a href="${escHub(pr.url)}" target="_blank" rel="noopener">PR #${pr.number}</a>`
                    + ` · ${escHub(pr.state || '')}${merge ? ' · ' + escHub(merge) : ''}`
                    + (pr.reviewDecision ? ` · review ${escHub(pr.reviewDecision)}` : '');
            } else if (onMain) {
                prLine.textContent = 'main — Ship prep (Claude 1×) 또는 Issue → Branch';
            } else {
                prLine.textContent = 'No open PR · Push 후 Open PR (EN)';
            }
        }
        updateShipButtonStates(onMain);
    } catch (e) {
        meta.textContent = e.message || 'GitHub 로드 실패';
    }
}

function hubIssueKey(siteId) {
    return `hubShipIssue_${siteId}`;
}

function hubSaveIssue(siteId, { number, title }) {
    if (!siteId || !number) return;
    try {
        sessionStorage.setItem(hubIssueKey(siteId), JSON.stringify({
            number: Number(number),
            title: String(title || '').trim(),
        }));
    } catch (_) {}
    window.__hubLastIssueNumber = Number(number);
    window.__hubLastIssueTitle = String(title || '').trim();
}

function hubLoadIssue(siteId) {
    const fallback = {
        number: window.__hubLastIssueNumber || null,
        title: window.__hubLastIssueTitle || '',
    };
    try {
        const raw = sessionStorage.getItem(hubIssueKey(siteId));
        if (!raw) return fallback;
        const data = JSON.parse(raw);
        return {
            number: data.number || fallback.number,
            title: data.title || fallback.title,
        };
    } catch (_) {
        return fallback;
    }
}

function updateShipButtonStates(onMain) {
    const prepBtn = document.getElementById('gh-btn-prep');
    const pushBtn = document.getElementById('gh-btn-push');
    const prBtn = document.getElementById('gh-btn-pr');
    const commitBtn = document.getElementById('gh-btn-commit');
    const reviewBtn = document.getElementById('gh-btn-review');
    const branchBtn = document.getElementById('gh-btn-branch');
    const mainHint = 'main에서는 불가 — Ship prep 사용';
    if (prepBtn) {
        prepBtn.disabled = false;
        prepBtn.title = onMain
            ? 'Issue → Branch → Commit → Push → PR (Claude 1×)'
            : 'Commit → Push → PR (Claude 1×, skips done steps)';
    }
    if (onMain) {
        if (pushBtn) { pushBtn.disabled = true; pushBtn.title = mainHint; }
        if (prBtn) { prBtn.disabled = true; prBtn.title = mainHint; }
        if (commitBtn) { commitBtn.disabled = true; commitBtn.title = mainHint; }
        if (reviewBtn) { reviewBtn.disabled = true; reviewBtn.title = mainHint; }
        if (branchBtn) { branchBtn.disabled = false; branchBtn.title = 'feature 브랜치 생성'; }
    } else {
        if (pushBtn) { pushBtn.disabled = false; pushBtn.title = '현재 feature 브랜치 push'; }
        if (prBtn) { prBtn.disabled = false; prBtn.title = ''; }
        if (commitBtn) { commitBtn.disabled = false; commitBtn.title = ''; }
        if (reviewBtn) { reviewBtn.disabled = false; reviewBtn.title = ''; }
        if (branchBtn) { branchBtn.disabled = false; branchBtn.title = '다른 브랜치로 전환/생성'; }
    }
}

const SHIP_PROGRESS_STEPS = [
    { id: 'draft', label: 'Claude draft' },
    { id: 'issue', label: 'Issue' },
    { id: 'branch', label: 'Branch' },
    { id: 'commit', label: 'Commit' },
    { id: 'push', label: 'Push' },
    { id: 'pr', label: 'Pull request' },
];

function shipStepIcon(status) {
    if (status === 'running') return '…';
    if (status === 'ok') return '✓';
    if (status === 'skip') return '↷';
    if (status === 'err') return '✗';
    return '○';
}

function initShipProgress() {
    const box = document.getElementById('github-ship-progress');
    const list = document.getElementById('github-ship-progress-steps');
    if (!box || !list) return;
    box.hidden = false;
    list.innerHTML = SHIP_PROGRESS_STEPS.map((s) => `
        <li class="pending" data-step="${escHub(s.id)}">
            <span class="ship-step-icon">○</span>
            <span class="ship-step-label">${escHub(s.label)}</span>
            <span class="ship-step-msg">—</span>
        </li>
    `).join('');
}

function setShipStep(stepId, status, message) {
    const row = document.querySelector(`#github-ship-progress-steps li[data-step="${stepId}"]`);
    if (!row) return;
    row.className = status;
    const icon = row.querySelector('.ship-step-icon');
    const msg = row.querySelector('.ship-step-msg');
    if (icon) icon.textContent = shipStepIcon(status);
    if (msg) msg.textContent = message || '';
}

function toggleShipManual(show) {
    const wrap = document.getElementById('github-ship-manual');
    const toggle = document.getElementById('gh-btn-manual-toggle');
    if (!wrap || !toggle) return;
    const open = show ?? wrap.hidden;
    wrap.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.textContent = open ? 'Manual steps ▾' : 'Manual steps ▸';
}

async function runShipPrep(siteId, hint) {
    initShipProgress();
    const prepBtn = document.getElementById('gh-btn-prep');
    if (prepBtn) prepBtn.disabled = true;

    const ctx = hubLoadIssue(siteId);
    let issueNum = ctx.number || null;
    let draft = null;

    try {
        setShipStep('draft', 'running', 'Issue · commit · PR (1× Claude)…');
        const draftRes = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/ship/draft`, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hint }),
        });
        draft = await draftRes.json();
        if (!draft.ok) {
            setShipStep('draft', 'err', draft.error || 'Draft failed');
            showToast(draft.error || 'Draft failed');
            return;
        }
        setShipStep('draft', 'ok', (draft.issue?.title || 'Draft ready').slice(0, 56));

        if (!issueNum) {
            setShipStep('issue', 'running', 'Creating on GitHub…');
            const ir = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/issue`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: draft.issue.title,
                    body: draft.issue.body || '',
                }),
            });
            const issue = await ir.json();
            if (!issue.ok) {
                setShipStep('issue', 'err', issue.error || 'Failed');
                showToast(issue.error || 'Issue failed');
                return;
            }
            issueNum = issue.number;
            hubSaveIssue(siteId, { number: issueNum, title: draft.issue.title });
            setShipStep('issue', 'ok', issue.url || `#${issueNum}`);
        } else {
            setShipStep('issue', 'skip', `Using #${issueNum}`);
        }

        const stRes = await fetch(`/api/sites/${encodeURIComponent(siteId)}/git/status`);
        const st = await stRes.json();
        const branch = st.branch || 'main';
        const onMain = branch === 'main' || branch === 'master';

        if (onMain) {
            setShipStep('branch', 'running', 'feat/… from issue');
            const br = await fetch(`/api/sites/${encodeURIComponent(siteId)}/git/branch`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    issue_number: issueNum,
                    issue_title: draft.issue.title,
                    hint: draft.branch_slug || '',
                }),
            });
            const brd = await br.json();
            if (!brd.ok) {
                setShipStep('branch', 'err', brd.error || 'Failed');
                showToast(brd.error || 'Branch failed');
                return;
            }
            setShipStep('branch', 'ok', brd.branch || brd.message || 'created');
        } else {
            setShipStep('branch', 'skip', branch);
        }

        const st2Res = await fetch(`/api/sites/${encodeURIComponent(siteId)}/git/status`);
        const st2 = await st2Res.json();
        if (st2.dirty) {
            setShipStep('commit', 'running', (draft.commit?.message || '').slice(0, 48));
            const cr = await fetch(`/api/sites/${encodeURIComponent(siteId)}/git/commit`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: draft.commit.message }),
            });
            const cd = await cr.json();
            if (!cd.ok) {
                setShipStep('commit', 'err', cd.error || 'Failed');
                showToast(cd.error || 'Commit failed');
                return;
            }
            setShipStep('commit', 'ok', cd.commit || cd.message || 'committed');
        } else {
            setShipStep('commit', 'skip', 'clean working tree');
        }

        setShipStep('push', 'running', 'git push -u origin…');
        const prs = await fetch(`/api/sites/${encodeURIComponent(siteId)}/push`, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ push_only: true }),
        });
        const pd = await prs.json();
        if (!prs.ok) {
            setShipStep('push', 'err', pd.error || pd.hint || 'Failed');
            showToast(pd.error || pd.hint || 'Push failed');
            return;
        }
        setShipStep('push', 'ok', pd.message || 'pushed');

        await refreshGitHubShip(siteId);
        const existingPr = window.__hubGithubPr?.pr;
        if (existingPr?.number) {
            setShipStep('pr', 'skip', `PR #${existingPr.number}`);
        } else {
            setShipStep('pr', 'running', 'Opening PR…');
            const prr = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/pr`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: draft.pr.title,
                    body: draft.pr.body,
                    summary: draft.pr.summary,
                    test_plan: draft.pr.test_plan,
                    issue_number: issueNum,
                }),
            });
            const prd = await prr.json();
            if (!prd.ok) {
                setShipStep('pr', 'err', prd.error || 'Failed');
                showToast(prd.error || 'PR failed');
                return;
            }
            setShipStep('pr', 'ok', prd.url || `PR #${prd.number}`);
        }

        showToast('PR ready — Review & merge');
        await refreshGitHubShip(siteId);
        refreshGitPanel(siteId);
        loadSiteWorkflow(siteId);
        if (window.__hubGithubPr?.pr?.number) {
            openShipReviewModal(siteId);
        }
    } catch (e) {
        showToast(e.message || 'Ship prep failed');
    } finally {
        if (prepBtn) prepBtn.disabled = false;
    }
}

function wireGitHubShip(siteId) {
    const actions = document.getElementById('github-ship-actions');
    if (!actions) return;
    actions.innerHTML = `
        <button type="button" class="btn btn-sm" id="gh-btn-prep">Ship prep</button>
        <button type="button" class="btn btn-sm" id="gh-btn-review">Review &amp; merge</button>
    `;
    const manual = document.getElementById('github-ship-manual');
    if (manual) {
        manual.innerHTML = `
            <button type="button" class="btn btn-ghost btn-sm" id="gh-btn-issue">Issue</button>
            <button type="button" class="btn btn-ghost btn-sm" id="gh-btn-branch">Branch</button>
            <button type="button" class="btn btn-ghost btn-sm" id="gh-btn-commit">Commit</button>
            <button type="button" class="btn btn-ghost btn-sm" id="gh-btn-push">Push</button>
            <button type="button" class="btn btn-ghost btn-sm" id="gh-btn-pr">PR</button>
        `;
    }
    const manualToggle = document.getElementById('gh-btn-manual-toggle');
    if (manualToggle) {
        manualToggle.onclick = () => toggleShipManual();
    }
    const prepBtn = document.getElementById('gh-btn-prep');
    const issueBtn = document.getElementById('gh-btn-issue');
    const branchBtn = document.getElementById('gh-btn-branch');
    const prBtn = document.getElementById('gh-btn-pr');
    const commitBtn = document.getElementById('gh-btn-commit');
    const pushBtn = document.getElementById('gh-btn-push');
    const reviewBtn = document.getElementById('gh-btn-review');
    if (prepBtn) {
        prepBtn.onclick = async () => {
            const hint = window.prompt('Optional hint (Korean OK) — Claude drafts issue/commit/PR once', '') || '';
            await runShipPrep(siteId, hint);
        };
    }
    if (issueBtn) {
        issueBtn.onclick = async () => {
            const hint = window.prompt('Optional hint (Korean OK) — used with git diff', '') || '';
            issueBtn.disabled = true;
            showToast('Drafting issue in English…');
            const draftRes = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/issue/draft`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hint }),
            });
            const draft = await draftRes.json();
            if (!draft.ok) {
                showToast(draft.error || 'Draft failed');
                issueBtn.disabled = false;
                return;
            }
            const preview = `${draft.title}\n\n${(draft.body || '').slice(0, 600)}${(draft.body || '').length > 600 ? '…' : ''}`;
            if (!window.confirm(`Create this issue?\n\n${preview}`)) {
                issueBtn.disabled = false;
                return;
            }
            const res = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/issue`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: draft.title,
                    body: draft.body || '',
                }),
            });
            const d = await res.json();
            showToast(d.url || d.error || (res.ok ? 'Issue created' : 'Failed'));
            if (d.number) hubSaveIssue(siteId, { number: d.number, title: draft.title });
            issueBtn.disabled = false;
            refreshGitHubShip(siteId);
        };
    }
    if (branchBtn) {
        branchBtn.onclick = async () => {
            const ctx = hubLoadIssue(siteId);
            if (!ctx.number) {
                showToast('Create issue (EN) 먼저');
                return;
            }
            branchBtn.disabled = true;
            showToast('Creating branch from issue…');
            const res = await fetch(`/api/sites/${encodeURIComponent(siteId)}/git/branch`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    issue_number: ctx.number,
                    issue_title: ctx.title,
                }),
            });
            const d = await res.json();
            showToast(d.message || d.error || (res.ok ? `Branch ${d.branch}` : 'Failed'));
            branchBtn.disabled = false;
            refreshGitPanel(siteId);
            refreshGitHubShip(siteId);
            loadSiteWorkflow(siteId);
        };
    }
    if (prBtn) {
        prBtn.onclick = async () => {
            const ctx = hubLoadIssue(siteId);
            const issue_number = ctx.number || null;
            prBtn.disabled = true;
            showToast('Drafting PR in English…');
            const draftRes = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/pr/draft`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ issue_number, hint: ctx.title || '' }),
            });
            const draft = await draftRes.json();
            if (!draft.ok) {
                showToast(draft.error || 'Draft failed');
                prBtn.disabled = false;
                return;
            }
            const preview = `${draft.title}\n\n${(draft.body || '').slice(0, 700)}${(draft.body || '').length > 700 ? '…' : ''}`;
            if (!window.confirm(`Open this PR?\n\n${preview}`)) {
                prBtn.disabled = false;
                return;
            }
            const res = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/pr`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: draft.title,
                    body: draft.body,
                    summary: draft.summary,
                    test_plan: draft.test_plan,
                    issue_number: draft.issue_number ?? issue_number,
                }),
            });
            const d = await res.json();
            showToast(d.url || d.error || (res.ok ? 'PR opened' : 'Failed'));
            prBtn.disabled = false;
            refreshGitHubShip(siteId);
        };
    }
    if (commitBtn) {
        commitBtn.onclick = async () => {
            const hint = window.prompt('Optional hint (Korean OK) — used with uncommitted diff', '') || '';
            commitBtn.disabled = true;
            showToast('Drafting commit message in English…');
            const draftRes = await fetch(`/api/sites/${encodeURIComponent(siteId)}/git/commit/draft`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hint }),
            });
            const draft = await draftRes.json();
            if (!draft.ok) {
                showToast(draft.error || 'Draft failed');
                commitBtn.disabled = false;
                return;
            }
            const preview = draft.message || '';
            if (!window.confirm(`Commit with this message?\n\n${preview}`)) {
                commitBtn.disabled = false;
                return;
            }
            const res = await fetch(`/api/sites/${encodeURIComponent(siteId)}/git/commit`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: draft.message }),
            });
            const d = await res.json();
            showToast(d.commit || d.error || (res.ok ? 'Committed' : 'Failed'));
            commitBtn.disabled = false;
            refreshGitPanel(siteId);
            refreshGitHubShip(siteId);
            loadSiteWorkflow(siteId);
        };
    }
    if (pushBtn) {
        pushBtn.onclick = async () => {
            if (window.__hubGithubCfg?.on_production_branch) {
                showToast('main에서는 Push 불가 — New branch 먼저');
                return;
            }
            pushBtn.disabled = true;
            const res = await fetch(`/api/sites/${encodeURIComponent(siteId)}/push`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ push_only: true }),
            });
            const d = await res.json();
            const msg = d.message || d.error || d.hint
                || (res.ok ? 'Pushed' : 'Failed');
            showToast(msg);
            pushBtn.disabled = false;
            refreshGitPanel(siteId);
            refreshGitHubShip(siteId);
            loadSiteWorkflow(siteId);
        };
    }
    if (reviewBtn) {
        reviewBtn.onclick = () => openShipReviewModal(siteId);
    }
    refreshGitHubShip(siteId);
    updateShipButtonStates(window.__hubGithubCfg?.on_production_branch);
}

function shipReviewChecklistOk() {
    return ['ship-review-chk-tests', 'ship-review-chk-secrets', 'ship-review-chk-read']
        .every((id) => document.getElementById(id)?.checked);
}

function updateShipReviewMergeBtn(review) {
    const mergeBtn = document.getElementById('ship-review-merge');
    if (!mergeBtn) return;
    const checksOk = shipReviewChecklistOk();
    const ready = checksOk && review?.can_merge;
    mergeBtn.disabled = !ready;
    if (!checksOk) {
        mergeBtn.title = '위 체크리스트 3개를 모두 선택하세요';
    } else if (!review?.can_merge) {
        mergeBtn.title = (review?.blockers || []).join(' · ') || '머지 불가';
    } else {
        mergeBtn.title = '';
    }
}

function closeShipReviewModal() {
    const overlay = document.getElementById('ship-review-overlay');
    if (!overlay) return;
    overlay.classList.remove('open');
    window.__hubShipReview = null;
}

async function openShipReviewModal(siteId) {
    const overlay = document.getElementById('ship-review-overlay');
    const titleEl = document.getElementById('ship-review-title');
    const metaEl = document.getElementById('ship-review-meta');
    const blockersEl = document.getElementById('ship-review-blockers');
    const statEl = document.getElementById('ship-review-stat');
    const diffEl = document.getElementById('ship-review-diff');
    const ghLink = document.getElementById('ship-review-github-link');
    const mergeBtn = document.getElementById('ship-review-merge');
    if (!overlay) {
        showToast('Review modal not found — refresh page');
        return;
    }

    showToast('Loading review…');

    ['ship-review-chk-tests', 'ship-review-chk-secrets', 'ship-review-chk-read'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
    });
    if (titleEl) titleEl.textContent = 'Review & merge';
    if (metaEl) metaEl.textContent = 'Loading…';
    if (blockersEl) { blockersEl.hidden = true; blockersEl.textContent = ''; }
    if (statEl) statEl.textContent = '—';
    if (diffEl) diffEl.textContent = '—';
    if (ghLink) ghLink.hidden = true;
    if (mergeBtn) mergeBtn.disabled = true;
    overlay.classList.add('open');

    try {
        const prNum = window.__hubGithubPr?.pr?.number;
        const url = `/api/sites/${encodeURIComponent(siteId)}/github/pr/review`
            + (prNum ? `?number=${encodeURIComponent(prNum)}` : '');
        const res = await fetch(url);
        const review = await res.json();
        window.__hubShipReview = review;
        if (!review.ok) {
            if (metaEl) metaEl.textContent = review.error || 'Review failed';
            if (blockersEl) {
                const items = (review.blockers || []).concat(review.error ? [review.error] : []);
                if (items.length) {
                    blockersEl.hidden = false;
                    blockersEl.textContent = items.join(' · ');
                }
            }
            return;
        }

        const pr = review.pr;
        if (titleEl) {
            titleEl.textContent = pr?.title
                ? `Review · PR #${pr.number}`
                : `Review · ${review.branch || 'branch'} → ${review.base || 'main'}`;
        }
        const src = review.source === 'github' ? 'GitHub PR' : 'local diff';
        const mergeTxt = pr?.mergeable === false ? ' · conflict' : (pr?.mergeable ? ' · mergeable' : '');
        if (metaEl) {
            metaEl.textContent = `${src}${pr?.url ? '' : ''} · ${review.stat || ''}${mergeTxt}`.trim();
        }
        if (statEl) statEl.textContent = review.stat || '(no stat)';
        if (diffEl) diffEl.textContent = review.empty ? '(empty diff)' : (review.diff || '—');
        if (ghLink && pr?.url) {
            ghLink.href = `${pr.url}/files`;
            ghLink.hidden = false;
        }
        if (blockersEl) {
            const blockers = review.blockers || [];
            if (blockers.length) {
                blockersEl.hidden = false;
                blockersEl.textContent = blockers.join(' · ');
            } else {
                blockersEl.hidden = true;
            }
        }
        updateShipReviewMergeBtn(review);
    } catch (e) {
        if (metaEl) metaEl.textContent = e.message || 'Review load failed';
    }
}

function wireShipReviewModal(siteId) {
    const overlay = document.getElementById('ship-review-overlay');
    const closeBtn = document.getElementById('ship-review-close');
    const mergeBtn = document.getElementById('ship-review-merge');
    if (!overlay || overlay.dataset.wired === '1') return;
    overlay.dataset.wired = '1';

    const onCheck = () => updateShipReviewMergeBtn(window.__hubShipReview);
    ['ship-review-chk-tests', 'ship-review-chk-secrets', 'ship-review-chk-read'].forEach((id) => {
        document.getElementById(id)?.addEventListener('change', onCheck);
    });

    const close = () => closeShipReviewModal();
    closeBtn?.addEventListener('click', close);
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) close();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay.classList.contains('open')) close();
    });

    if (mergeBtn) {
        mergeBtn.onclick = async () => {
            const review = window.__hubShipReview;
            if (!review?.can_merge || !shipReviewChecklistOk()) return;
            const num = review.pr?.number || window.__hubGithubPr?.pr?.number;
            if (!window.confirm(`Squash merge PR${num ? ' #' + num : ''} to main?`)) return;
            mergeBtn.disabled = true;
            const res = await fetch(`/api/sites/${encodeURIComponent(siteId)}/github/pr/merge`, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ number: num || null, squash: true, delete_branch: true }),
            });
            const d = await res.json();
            if (res.ok) {
                showToast('Merged to main · Deploy 탭에서 배포');
                closeShipReviewModal();
            } else {
                showToast(d.error || d.message || 'Merge failed');
            }
            mergeBtn.disabled = false;
            refreshGitHubShip(siteId);
            refreshGitPanel(siteId);
            loadSiteWorkflow(siteId);
        };
    }
}

function parseDeployMtime(mtime) {
    if (!mtime) return NaN;
    return Date.parse(String(mtime).replace(' ', 'T'));
}

function isProductionBranch(branch) {
    const b = (branch || 'main').trim();
    return b === 'main' || b === 'master';
}

function deployStatus(site, logs) {
    const git = site?.git_summary || {};
    if (!site?.has_deploy) {
        return { kind: 'none', badge: '', text: 'deploy.sh 없음' };
    }
    const branch = git.branch || 'main';
    if (!isProductionBranch(branch)) {
        return {
            kind: 'blocked',
            badge: '<span class="badge badge-dirty">main만</span>',
            text: `현재 브랜치 ${branch} · PR 머지 후 main에서 Deploy`,
        };
    }
    if (git.dirty) {
        return {
            kind: 'blocked',
            badge: '<span class="badge badge-dirty">Git 먼저</span>',
            text: '미커밋 변경 있음 · Ship에서 Commit (EN)',
        };
    }
    if ((git.ahead || 0) > 0) {
        return {
            kind: 'blocked',
            badge: '<span class="badge badge-dirty">Push 필요</span>',
            text: `Push 안 된 커밋 ${git.ahead}개 · Ship에서 Push`,
        };
    }
    // Git push stubs share deploy-*.log names — only Cloud Deploy counts here.
    const dep = (logs.deploy || []).find((d) => (d.kind || 'deploy') === 'deploy');
    if (dep?.state === 'failed') {
        return {
            kind: 'ready',
            badge: '<span class="badge badge-dirty">재배포</span>',
            text: '직전 배포 실패 · Deploy 가능',
        };
    }
    const commitAt = git.last_commit_at ? Date.parse(git.last_commit_at) : NaN;
    const deployAt = dep?.mtime ? parseDeployMtime(dep.mtime) : NaN;
    if (!dep) {
        return {
            kind: 'ready',
            badge: '<span class="badge badge-dirty">배포 필요</span>',
            text: '배포 기록 없음 · Deploy 가능',
        };
    }
    if (!Number.isNaN(commitAt) && !Number.isNaN(deployAt) && commitAt > deployAt) {
        return {
            kind: 'ready',
            badge: '<span class="badge badge-dirty">배포 필요</span>',
            text: 'Push 이후 미배포 · Deploy 하세요',
        };
    }
    return {
        kind: 'ok',
        badge: '<span class="badge badge-clean">최신</span>',
        text: '배포할 변경 없음 (최근 배포됨)',
    };
}

async function refreshGitPanel(siteId) {
    const row = document.getElementById('git-status-row');
    const meta = document.getElementById('git-files-meta');
    const statEl = document.getElementById('git-diff-stat');
    const diffEl = document.getElementById('git-diff-body');
    if (!row) return;
    row.textContent = '로딩…';
    try {
        const [stRes, diffRes] = await Promise.all([
            fetch(`/api/sites/${encodeURIComponent(siteId)}/git/status`),
            fetch(`/api/sites/${encodeURIComponent(siteId)}/git/diff`),
        ]);
        const st = await stRes.json();
        const diff = await diffRes.json();
        if (!st.ok) {
            row.innerHTML = `<span class="mono" style="color:#a66">${escHub(st.error || 'Git 오류')}</span>`;
            return;
        }
        const badge = st.dirty
            ? '<span class="badge badge-dirty">dirty</span>'
            : '<span class="badge badge-clean">clean</span>';
        row.innerHTML = `${badge}<span class="mono">${escHub(st.branch || 'main')}</span>
            <span class="mono" style="color:#888;margin-left:8px">${escHub(st.status_line || '')}</span>`;
        if (meta) {
            meta.textContent = st.dirty
                ? `변경 ${st.file_count || 0}개`
                : '커밋할 변경 없음';
        }
        if (statEl) statEl.textContent = diff.stat || '(stat 없음)';
        if (diffEl) diffEl.textContent = diff.empty ? '(diff 없음)' : (diff.diff || '—');
    } catch (e) {
        row.innerHTML = `<span class="mono" style="color:#a66">${escHub(e.message || '오류')}</span>`;
    }
}

function wireDeployPanel(siteId) {
    /* Actions filled in renderDeployActions */
}

function renderDeployActions(site, logs) {
    const actionsEl = document.getElementById('deploy-actions');
    const statusRow = document.getElementById('deploy-status-row');
    const metaEl = document.getElementById('deploy-recent-meta');
    const listEl = document.getElementById('deploy-log-list');
    if (!actionsEl) return;
    if (site?.id && typeof hubIsViewingSite === 'function' && !hubIsViewingSite(site.id)) return;

    const depSt = deployStatus(site, logs);
    if (statusRow) {
        statusRow.innerHTML = depSt.badge
            ? `${depSt.badge}<span class="mono" style="margin-left:8px">${escHub(depSt.text)}</span>`
            : `<span class="mono" style="color:#888">${escHub(depSt.text)}</span>`;
    }

    if (!site) {
        actionsEl.innerHTML = '';
        return;
    }

    if (site.has_deploy) {
        const running = !!window.__hubDeployRunningBySite?.[site.id];
        const pipeRunning = typeof pipelineForSite === 'function' && !!pipelineForSite(site.id)?.running;
        const branch = site.git_summary?.branch || 'main';
        const deployBlocked = depSt.kind === 'blocked' || !isProductionBranch(branch);
        actionsEl.innerHTML = running
            ? `<button type="button" class="btn" id="hub-git-deploy" disabled>배포 중…</button>`
            : (pipeRunning
                ? `<button type="button" class="btn" id="hub-git-deploy" disabled title="콘텐츠 생성 중">Deploy</button>`
                : `<button type="button" class="btn" id="hub-git-deploy" title="Production · main only" ${deployBlocked ? 'disabled' : ''}>Deploy</button>`);
        const depBtn = document.getElementById('hub-git-deploy');
        if (depBtn && !running && !pipeRunning && !deployBlocked) {
            depBtn.onclick = () => startHubDeploy(site);
        }
    } else {
        actionsEl.innerHTML = '<span class="mono" style="color:#888">deploy.sh 없음</span>';
    }

    const deps = logs.deploy || [];
    if (metaEl) {
        if (!deps.length) {
            metaEl.textContent = '최근 배포 기록 없음';
        } else {
            const latestGit = deps.find((d) => d.kind === 'git');
            const latestDep = deps.find((d) => (d.kind || 'deploy') === 'deploy');
            const bits = [];
            if (latestGit) bits.push(`Git ${latestGit.mtime}`);
            if (latestDep) {
                const st = latestDep.state === 'success' ? '성공' : (latestDep.state === 'failed' ? '실패' : latestDep.state);
                bits.push(`배포 ${latestDep.mtime} (${st})`);
            }
            metaEl.textContent = (bits.length ? bits.join(' · ') : `최근 ${deps[0].mtime}`) + ` · ${deps.length}건`;
        }
    }
    if (listEl) {
        const rows = deps.map(d => {
            const isGit = d.kind === 'git';
            const kindLabel = isGit ? 'Git' : '배포';
            const kindClass = isGit ? 'dep-kind-git' : 'dep-kind-deploy';
            const st = d.state === 'success' ? '성공' : (d.state === 'failed' ? '실패' : d.state);
            const stClass = d.state === 'success' ? 'dep-st-ok' : (d.state === 'failed' ? 'dep-st-fail' : '');
            return `<li class="deploy-log-item" data-log-file="${escHub(d.file)}" data-kind="${escHub(d.kind || 'deploy')}" title="전체 로그 보기">`
                + `<span><span class="dep-kind ${kindClass}">${kindLabel}</span>`
                + ` <span class="${stClass}">${escHub(st)}</span> · ${escHub(d.mtime)}</span>`
                + `<span class="dep-file">${escHub(d.file)}</span></li>`;
        });
        listEl.innerHTML = rows.length ? rows.join('') : '<li style="color:#666">기록 없음</li>';
        listEl.querySelectorAll('.deploy-log-item').forEach(li => {
            li.onclick = () => openDeployLog(site.id, li.getAttribute('data-log-file'));
        });
    }
}

async function openDeployLog(siteId, filename) {
    if (!siteId || !filename) return;
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress('로그', filename, { siteId, kind: 'log' });
    }
    try {
        const res = await fetch(
            `/api/sites/${encodeURIComponent(siteId)}/deploy/logs/${encodeURIComponent(filename)}`,
            { credentials: 'same-origin' }
        );
        const d = await res.json();
        if (!res.ok || !d.ok) {
            if (typeof hubOpenResult === 'function') {
                hubOpenResult({
                    title: '로그', meta: filename, error: d.error || '로그를 열 수 없습니다',
                    siteId, kind: 'log',
                });
            } else if (typeof showToast === 'function') {
                showToast(d.error || '로그 로드 실패');
            }
            return;
        }
        const note = d.truncated ? ' · 앞부분 생략(최근만)' : '';
        const kindTitle = d.kind === 'git' ? 'Git 로그' : '배포 로그';
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: kindTitle,
                meta: `${d.file || filename} · ${d.mtime || ''}${note}`,
                logFull: d.text || '',
                siteId, kind: 'log',
            });
            const pre = document.querySelector('#hub-results-body .hub-modal-log');
            if (pre) pre.style.maxHeight = '60vh';
        }
    } catch (e) {
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: '로그', meta: filename, error: e.message || '로드 실패',
                siteId, kind: 'log',
            });
        }
    }
}

function setDeployStatusRow(html, siteId) {
    if (typeof hubSetDeployStatusRow === 'function') {
        hubSetDeployStatusRow(html, siteId);
        return;
    }
    if (siteId != null && typeof hubIsViewingSite === 'function' && !hubIsViewingSite(siteId)) return;
    const statusRow = document.getElementById('deploy-status-row');
    if (statusRow) statusRow.innerHTML = html;
}

async function startHubDeploy(site) {
    if (!site?.id) return;
    if (window.__hubDeployRunningBySite?.[site.id]) return;
    const pipe = typeof pipelineForSite === 'function' ? pipelineForSite(site.id) : null;
    if (pipe?.running) {
        if (typeof showToast === 'function') showToast('콘텐츠 생성이 진행 중입니다. 끝난 뒤 배포하세요');
        return;
    }
    window.__hubDeployRunningBySite = window.__hubDeployRunningBySite || {};
    window.__hubDeployRunningBySite[site.id] = true;
    window.__hubDeployRunning = true;
    const depBtn = document.getElementById('hub-git-deploy');
    if (depBtn) {
        depBtn.disabled = true;
        depBtn.textContent = '배포 중…';
    }
    setDeployStatusRow(
        '<span class="badge badge-dirty">진행 중</span>'
        + '<span class="mono" style="margin-left:8px">Deploy 버튼 눌림 · Cloud Build 요청 중…</span>',
        site.id,
    );
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress('④ 배포 중…', `${site.label || site.id} · 시작 요청`, {
            siteId: site.id, siteLabel: site.label || site.id, kind: 'deploy',
        });
    }
    if (typeof showToast === 'function') showToast('배포 시작 요청…');

    try {
        const res = await fetch(`/api/sites/${encodeURIComponent(site.id)}/deploy`, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
        });
        const d = await res.json();
        if (!d.job_id) {
            const err = d.error || d.message || 'Deploy 시작 실패';
            setDeployStatusRow(
                '<span class="badge badge-dirty">실패</span>'
                + `<span class="mono" style="margin-left:8px;color:#f88">${escHub(err)}</span>`,
                site.id,
            );
            if (typeof hubOpenResult === 'function') {
                hubOpenResult({
                    title: '배포 실패', meta: site.label || site.id, error: err,
                    siteId: site.id, kind: 'deploy',
                });
            }
            if (typeof showToast === 'function') showToast('배포 실패: ' + err);
            return;
        }
        setDeployStatusRow(
            '<span class="badge badge-dirty">진행 중</span>'
            + '<span class="mono" style="margin-left:8px">배포 진행 중… (Cloud Build)</span>',
            site.id,
        );
        if (typeof showToast === 'function') showToast('배포 진행 중');
        if (typeof hubPersistProgress === 'function') {
            hubPersistProgress({
                kind: 'deploy',
                siteId: site.id,
                siteLabel: site.label || site.id,
                jobId: d.job_id,
                title: '④ 배포 중…',
                meta: `${site.label || site.id} · job ${d.job_id}`,
                minimized: false,
                startedAt: Date.now(),
                state: 'running',
            }, site.id);
        }
        if (typeof hubUpdateProgress === 'function') {
            hubUpdateProgress({
                title: '④ 배포 중…',
                meta: `${site.label || site.id} · job ${d.job_id}`,
                state: 'running',
                running: true,
                lines: ['Cloud Build 진행 중…', `job: ${d.job_id}`],
                logFull: '',
                siteId: site.id,
                kind: 'deploy',
            });
        }
        await pollHubDeploy(site, d.job_id);
    } catch (e) {
        const err = e.message || 'Deploy 요청 실패';
        setDeployStatusRow(
            '<span class="badge badge-dirty">실패</span>'
            + `<span class="mono" style="margin-left:8px;color:#f88">${escHub(err)}</span>`,
            site.id,
        );
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: '배포 실패', meta: site.label || site.id, error: err,
                siteId: site.id, kind: 'deploy',
            });
        }
        if (typeof showToast === 'function') showToast('배포 실패: ' + err);
    } finally {
        if (window.__hubDeployRunningBySite) delete window.__hubDeployRunningBySite[site.id];
        window.__hubDeployRunning = Object.values(window.__hubDeployRunningBySite || {}).some(Boolean);
        if (typeof hubIsViewingSite !== 'function' || hubIsViewingSite(site.id)) {
            loadSiteWorkflow(site.id);
        }
    }
}

async function pollHubDeploy(site, jobId) {
    if (typeof hubPollDeployJob === 'function') {
        const saved = typeof hubLoadProgress === 'function' ? hubLoadProgress(site.id) : null;
        return hubPollDeployJob({
            kind: 'deploy',
            siteId: site.id,
            siteLabel: site.label || site.id,
            jobId,
            title: '④ 배포 중…',
            meta: `${site.label || site.id} · job ${jobId}`,
            startedAt: (saved?.jobId === jobId && saved.startedAt) ? saved.startedAt : Date.now(),
        });
    }
    // Fallback if hub_modal.js not loaded
    const maxMs = 45 * 60 * 1000;
    const started = Date.now();
    const label = site.label || site.id;
    while (Date.now() - started < maxMs) {
        await new Promise(r => setTimeout(r, 3000));
        let d;
        try {
            const res = await fetch(
                `/api/sites/${encodeURIComponent(site.id)}/deploy/status?job_id=${encodeURIComponent(jobId)}`,
                { credentials: 'same-origin' }
            );
            d = await res.json();
            if (!res.ok || d.error) {
                const err = d.error || '상태 조회 실패';
                setDeployStatusRow(
                    '<span class="badge badge-dirty">실패</span>'
                    + `<span class="mono" style="margin-left:8px;color:#f88">${escHub(err)}</span>`,
                    site.id,
                );
                if (typeof hubOpenResult === 'function') {
                    hubOpenResult({ title: '배포 실패', meta: label, error: err, logFull: d.log_tail || '' });
                }
                if (typeof showToast === 'function') showToast('배포 실패: ' + err);
                return false;
            }
        } catch (e) {
            continue;
        }

        const msg = d.message || d.state || '';
        if (d.state === 'unknown') {
            setDeployStatusRow(
                '<span class="badge badge-dirty">확인 필요</span>'
                + `<span class="mono" style="margin-left:8px">${escHub(msg || '서버 재시작으로 추적 끊김 · 로그 확인')}</span>`,
                site.id,
            );
            if (typeof hubOpenResult === 'function') {
                hubOpenResult({
                    title: '배포 상태 확인',
                    meta: label,
                    error: msg || '백그라운드 추적 불가 · 아래 로그를 확인하세요',
                    logFull: d.log_tail || '',
                });
            }
            if (typeof showToast === 'function') showToast('배포 상태 불명 · 로그 확인');
            return null;
        }
        if (d.state === 'running') {
            setDeployStatusRow(
                '<span class="badge badge-dirty">진행 중</span>'
                + `<span class="mono" style="margin-left:8px">${escHub(msg || '배포 진행 중…')}</span>`,
                site.id,
            );
            if (typeof hubUpdateProgress === 'function') {
                hubUpdateProgress({
                    title: '④ 배포 중…',
                    meta: `${label} · 진행 중`,
                    state: 'running',
                    running: true,
                    lines: [msg || 'Cloud Build 진행 중…'],
                    logFull: d.log_tail || '',
                });
            }
            continue;
        }
        if (d.state === 'success') {
            setDeployStatusRow(
                '<span class="badge badge-clean">성공</span>'
                + '<span class="mono" style="margin-left:8px">배포 완료</span>',
                site.id,
            );
            if (typeof hubOpenResult === 'function') {
                hubOpenResult({
                    title: '배포 성공',
                    meta: label,
                    lines: ['배포 완료', msg].filter(Boolean),
                    logFull: d.log_tail || '',
                });
            }
            if (typeof showToast === 'function') showToast('배포 성공');
            return true;
        }
        if (d.state === 'failed') {
            const reason = d.error_summary || d.message || '배포 실패';
            setDeployStatusRow(
                '<span class="badge badge-dirty">실패</span>'
                + `<span class="mono" style="margin-left:8px;color:#f88">${escHub(reason)}</span>`,
                site.id,
            );
            if (typeof hubOpenResult === 'function') {
                hubOpenResult({
                    title: '배포 실패',
                    meta: label,
                    error: reason,
                    lines: ['배포 실패', reason],
                    logFull: d.log_tail || '',
                });
            }
            if (typeof showToast === 'function') showToast('배포 실패: ' + reason);
            return false;
        }
    }
    const timeoutMsg = '45분 내 완료 신호 없음';
    setDeployStatusRow(
        '<span class="badge badge-dirty">실패</span>'
        + `<span class="mono" style="margin-left:8px;color:#f88">${timeoutMsg}</span>`,
        site.id,
    );
    if (typeof hubOpenResult === 'function') {
        hubOpenResult({ title: '배포 타임아웃', meta: label, error: timeoutMsg });
    }
    if (typeof showToast === 'function') showToast('배포 타임아웃 · 로그 확인');
    return false;
}
function updateWorkflowStrip(site, logs, pipe) {
    const current = normalizeSection(new URLSearchParams(location.search).get('section'));
    const remain = typeof remainingText === 'function' ? remainingText(pipe || {}) : '—';
    const contentSt = (logs.content_schedule && logs.content_schedule.status) || 'never';
    const gscSt = (logs.gsc_schedule && logs.gsc_schedule.status) || 'never';

    const cLabel = document.getElementById('wf-content-label');
    const cMeta = document.getElementById('wf-content-meta');
    if (cLabel) {
        const siteId = pipe?.site_id || '';
        const raw = typeof generatableText === 'function'
            ? generatableText(pipelineBacklogSnap(pipe), siteId)
            : (remain === '없음' ? '0건' : remain);
        if (siteId === 'krcare') {
            cLabel.textContent = raw === '—' ? 'TourAPI 수집' : raw;
        } else {
            cLabel.textContent = (typeof isAiQueueSite === 'function' && isAiQueueSite(siteId))
                ? `생성 가능 ${raw}`
                : (raw === '—' ? 'MD 대기 0건' : raw);
        }
    }
    if (cMeta) cMeta.textContent = logs.content_due_label || '7일 주기';
    const cStep = document.getElementById('wf-content');
    if (cStep) {
        cStep.className = 'wf-step ' + wfStepClass(contentSt) + (current === 'content' ? ' active' : '');
    }

    const sLabel = document.getElementById('wf-seo-label');
    const sMeta = document.getElementById('wf-seo-meta');
    if (sLabel) sLabel.textContent = logs.gsc_due_label || 'SEO';
    if (sMeta) sMeta.textContent = logs.last_gsc_response_at ? `최근 ${logs.last_gsc_response_at}` : '실행 기록 없음';
    const sStep = document.getElementById('wf-seo');
    if (sStep) {
        sStep.className = 'wf-step ' + wfStepClass(gscSt) + (current === 'seo' ? ' active' : '');
    }

    const git = site?.git_summary;
    const gLabel = document.getElementById('wf-git-label');
    const gMeta = document.getElementById('wf-git-meta');
    if (gLabel) gLabel.textContent = git?.dirty ? 'Push 필요' : (git ? 'clean' : '—');
    if (gMeta) gMeta.textContent = git?.branch || 'status · diff';
    const gStep = document.getElementById('wf-git');
    if (gStep) {
        gStep.className = 'wf-step ' + (git?.dirty ? 'wf-warn' : '') + (current === 'git' ? ' active' : '');
    }

    const dLabel = document.getElementById('wf-deploy-label');
    const dMeta = document.getElementById('wf-deploy-meta');
    const deps = logs.deploy || [];
    const depSt = deployStatus(site, logs);
    if (dLabel) {
        dLabel.textContent = !site?.has_deploy ? '—'
            : (depSt.kind === 'ready' ? '배포 필요' : (depSt.kind === 'blocked' ? 'Git 먼저' : 'Cloud Build'));
    }
    if (dMeta) {
        dMeta.textContent = depSt.kind === 'ready' ? 'Deploy 가능'
            : (depSt.kind === 'blocked' ? depSt.text.split(' · ')[0]
                : (deps[0] ? `최근 ${deps[0].mtime}` : '배포 기록'));
    }
    const dStep = document.getElementById('wf-deploy');
    if (dStep) {
        const warn = depSt.kind === 'ready' || depSt.kind === 'blocked';
        dStep.className = 'wf-step' + (warn ? ' wf-warn' : '') + (current === 'deploy' ? ' active' : '');
    }

    const mStep = document.getElementById('wf-metrics');
    const mMeta = document.getElementById('wf-metrics-meta');
    if (mMeta) mMeta.textContent = 'GA4 · GSC 차트';
    if (mStep) mStep.className = 'wf-step' + (current === 'metrics' ? ' active' : '');

    const iStep = document.getElementById('wf-images');
    if (iStep) iStep.className = 'wf-step' + (current === 'images' ? ' active' : '');
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
