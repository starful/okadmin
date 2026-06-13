/** Content pipeline UI — shared by dashboard (and legacy ops redirect). */
let activePipelineSite = '';
let pipelinePoll = null;
let backlogBootstrapDone = false;

function escPipeline(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function remainingText(b) {
    const bl = b.backlog || {};
    const bits = [];
    if (bl.items_pairs) bits.push(`아이템 ${bl.items_pairs}`);
    if (bl.guides_topics) bits.push(`가이드 ${bl.guides_topics}`);
    if (bl.guides_md) bits.push(`가이드 ${bl.guides_md}`);
    if (bl.korean_files) bits.push(`한국어 ${bl.korean_files}`);
    if (bl.images) bits.push(`이미지 ${bl.images}`);
    return bits.length ? bits.join(' · ') : '없음';
}

function backlogHtml(p) {
    const b = p.backlog;
    const refreshBtn = (siteId, disabled) =>
        `<button type="button" class="btn btn-ghost btn-sm" onclick="refreshBacklog('${escPipeline(siteId)}')" ${disabled ? 'disabled' : ''}>건수 새로고침</button>`;
    const actions = (r, e) => `<div class="pipe-actions">${r}${e || ''}</div>`;
    if (!b) {
        return `<div class="dash-pipeline">
            <p class="pipe-summary">남은 건수: —</p>
            ${actions(refreshBtn(p.site_id, false), '')}
        </div>`;
    }
    const exp = b.csv_expand || {};
    const expandBtn = (exp.items_expandable || exp.guides_expandable)
        ? `<button type="button" class="btn btn-ghost btn-sm" onclick="expandCsv('${escPipeline(p.site_id)}')" ${p.running ? 'disabled' : ''}>CSV 추가</button>`
        : '';
    return `<div class="dash-pipeline">
        <p class="pipe-summary">남은 건수: ${escPipeline(remainingText(b))}</p>
        ${actions(refreshBtn(p.site_id, p.running), expandBtn)}
    </div>`;
}

function pipelineActionsHtml(p) {
    if (!p) return '';
    const cls = p.running ? 'running' : '';
    return `<div class="dash-pipeline-wrap ${cls}" data-pipeline-site="${escPipeline(p.site_id)}">
        ${backlogHtml(p)}
        <button type="button" class="btn btn-primary pipe-run" ${p.available && !p.running ? '' : 'disabled'}
            onclick="runPipeline('${escPipeline(p.site_id)}', '${escPipeline(p.label)}')">
            ${p.running ? (p.phase === 'deploy' ? '② 배포 중…' : '① 생성 중…') : '콘텐츠 생성'}
        </button>
    </div>`;
}

function pipelineForSite(siteId) {
    return (window.__pipelines || []).find(p => p.site_id === siteId);
}

function setResultBadge(kind, text) {
    const el = document.getElementById('result-badge');
    if (!el) return;
    el.className = 'result-badge ' + kind;
    el.textContent = text;
}

function renderPhaseTrack(phase, running) {
    const track = document.getElementById('phase-track');
    const gen = document.getElementById('phase-generate');
    const dep = document.getElementById('phase-deploy');
    if (!track || !gen || !dep) return;
    if (!running) {
        track.style.display = 'none';
        gen.className = 'phase-step';
        dep.className = 'phase-step';
        return;
    }
    track.style.display = 'flex';
    if (phase === 'deploy') {
        gen.className = 'phase-step done';
        dep.className = 'phase-step active';
    } else {
        gen.className = 'phase-step active';
        dep.className = 'phase-step';
    }
}

function renderSummary(summary, logTail, lastRun, opts) {
    const linesEl = document.getElementById('summary-lines');
    const snipEl = document.getElementById('log-snippet');
    const logLabel = document.getElementById('log-label');
    const fullWrap = document.getElementById('log-full');
    const fullPre = document.getElementById('log-full-text');
    const siteEl = document.getElementById('result-site');
    if (!linesEl) return;

    const phase = opts?.phase || null;
    const running = !!opts?.running;
    renderPhaseTrack(phase, running);

    if (lastRun?.last_run_display && siteEl && !running) {
        const st = lastRun.last_run_ok === true ? '완료' : (lastRun.last_run_ok === false ? '실패' : '');
        const base = siteEl.textContent.replace(/\s*·\s*마지막.*$/, '').trim();
        siteEl.textContent = base + ' · 마지막 ' + lastRun.last_run_display + (st ? ' ' + st : '');
    }

    const title = summary?.title || '—';
    if (title === '완료') setResultBadge('ok', '완료');
    else if (title === '실패') setResultBadge('err', '실패');
    else if (title === '배포 중') setResultBadge('run', '② 배포 중');
    else if (title === '생성 중') setResultBadge('run', '① 생성 중');
    else if (title === '실행 중') setResultBadge('run', '실행 중');
    else setResultBadge('idle', title);

    const lines = summary?.lines?.length ? summary.lines : ['결과 없음'];
    linesEl.innerHTML = lines.map(l => `<li>${escPipeline(l)}</li>`).join('');

    const snip = (summary?.log_snippet || '').trim();
    if (snipEl && logLabel) {
        if (snip) {
            logLabel.style.display = 'block';
            logLabel.textContent = phase === 'deploy' && running ? 'deploy.sh 로그 (실시간)' : '파이프라인 로그';
            snipEl.style.display = 'block';
            snipEl.textContent = snip;
        } else {
            logLabel.style.display = 'none';
            snipEl.style.display = 'none';
        }
    }

    const fullText = (opts?.deploy_log_tail && running && phase === 'deploy')
        ? opts.deploy_log_tail + '\n\n--- pipeline ---\n\n' + (logTail || '')
        : (logTail || '');
    if (fullWrap && fullPre) {
        if (fullText && fullText.length > 80) {
            fullWrap.style.display = 'block';
            fullPre.textContent = fullText;
        } else {
            fullWrap.style.display = 'none';
        }
    }
}

function updatePipelineCardStates() {
    const siteId = activePipelineSite;
    document.querySelectorAll('.dash-card[data-site-id]').forEach(card => {
        const sid = card.dataset.siteId;
        const p = pipelineForSite(sid);
        card.classList.remove('pipe-running', 'pipe-done-ok', 'pipe-done-err');
        if (p?.running || (siteId === sid && p?.running)) card.classList.add('pipe-running');
        else if (siteId === sid && p?.last_ok === true) card.classList.add('pipe-done-ok');
        else if (siteId === sid && p?.last_ok === false) card.classList.add('pipe-done-err');
    });
}

async function loadPipelines() {
    try {
        const res = await fetch('/api/content/pipelines');
        window.__pipelines = await res.json();
    } catch (_) {
        window.__pipelines = [];
    }
    if (!backlogBootstrapDone && window.__pipelines.some(p => !p.backlog)) {
        backlogBootstrapDone = true;
        bootstrapBacklog();
    }
    if (typeof window.rerenderDashboard === 'function') window.rerenderDashboard();
    const running = window.__pipelines.find(p => p.running);
    if (running && !pipelinePoll) {
        activePipelineSite = running.site_id;
        const siteEl = document.getElementById('result-site');
        if (siteEl) siteEl.textContent = '· ' + running.label;
        pipelinePoll = setInterval(pollActivePipeline, 1500);
        pollActivePipeline();
    }
    updatePipelineCardStates();
}

async function runPipeline(siteId, label) {
    activePipelineSite = siteId;
    const siteEl = document.getElementById('result-site');
    if (siteEl) siteEl.textContent = '· ' + (label || siteId);
    const panel = document.getElementById('result-panel');
    if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setResultBadge('run', '시작');
    renderSummary({ title: '생성 중', lines: ['① 콘텐츠 생성을 시작합니다…'] }, '', null, { running: true, phase: 'generate' });

    const res = await fetch('/api/content/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: siteId }),
    });
    const d = await res.json();
    if (!res.ok) {
        setResultBadge('err', '오류');
        renderSummary({ title: '실패', lines: [d.error || '시작 실패'] }, '', null);
        return;
    }
    showToast((label || siteId) + ' 생성 시작');
    if (pipelinePoll) clearInterval(pipelinePoll);
    pipelinePoll = setInterval(pollActivePipeline, 1500);
    pollActivePipeline();
    loadPipelines();
}

async function pollActivePipeline() {
    if (!activePipelineSite) return;
    const siteId = activePipelineSite;
    const res = await fetch('/api/content/pipeline/result?site_id=' + encodeURIComponent(siteId));
    const d = await res.json();
    renderSummary(d.summary, d.log_tail || '', {
        last_run_display: d.last_run_display,
        last_run_ok: d.last_run_ok,
    }, {
        running: d.running,
        phase: d.phase,
        deploy_log_tail: d.deploy_log_tail,
    });

    if (d.running) {
        document.querySelectorAll('.dash-pipeline-wrap').forEach(c => {
            c.classList.toggle('running', c.dataset.pipelineSite === siteId);
        });
        updatePipelineCardStates();
        return;
    }

    clearInterval(pipelinePoll);
    pipelinePoll = null;
    loadPipelines();

    if (d.ok) showToast(siteId + ' 완료');
    else if (d.ok === false) showToast(siteId + ' 실패');
}

async function refreshBacklog(siteId, { silent = false } = {}) {
    const btn = document.getElementById('btn-refresh-all-backlog');
    if (!siteId && btn) btn.disabled = true;
    const res = await fetch('/api/content/pipeline/backlog/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(siteId ? { site_id: siteId } : {}),
    });
    const d = await res.json();
    if (!siteId && btn) btn.disabled = false;
    if (!res.ok) {
        if (!silent) showToast(d.error || '건수 새로고침 실패');
        return false;
    }
    if (!silent) showToast(siteId ? '건수 갱신됨' : '전체 건수 갱신됨');
    await loadPipelines();
    return true;
}

async function bootstrapBacklog() {
    await refreshBacklog(null, { silent: true });
}

async function expandCsv(siteId) {
    if (!confirm('CSV에 시드/확장 행을 추가합니다. 계속할까요?')) return;
    const res = await fetch('/api/content/pipeline/csv-expand', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: siteId }),
    });
    const d = await res.json();
    if (!res.ok) {
        showToast(d.error || 'CSV 갱신 실패');
        return;
    }
    showToast('CSV 추가 완료');
    loadPipelines();
}
