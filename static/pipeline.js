/** Content pipeline UI — shared by dashboard (and legacy ops redirect). */
let activePipelineSite = '';
let pipelinePoll = null;
let backlogBootstrapDone = false;

function escPipeline(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function pipelineBacklogSnap(p) {
    const root = (p && p.backlog) || null;
    return root && typeof root === 'object' ? root : null;
}

function csvExpandAvail(snap) {
    const exp = (snap && snap.csv_expand) || {};
    return (exp.items_expandable || 0) + (exp.guides_expandable || 0);
}

/** Human-readable generatable content + guide counts (MD not yet built). */
function generatableText(snap, siteId) {
    if (!snap) return '—';
    if (snap.summary) return snap.summary;
    const g = snap.generatable || {};
    const content = g.content || 0;
    const guides = g.guides || 0;
    if (siteId === 'okstats') return `인사이트 ${content} · 가이드 ${guides}`;
    if (siteId === 'starful.biz') return `가이드 ${guides}`;
    if (siteId === 'jpcampus' || siteId === 'krcampus') return `가이드 ${guides}`;
    if (siteId === 'okramen' || siteId === 'okonsen' || siteId === 'okcaddie') {
        return `아이템 ${content} · 가이드 ${guides}`;
    }
    return `콘텐츠 ${content} · 가이드 ${guides}`;
}

function generatableHtml(snap, siteId) {
    const text = generatableText(snap, siteId);
    return `<span class="gen-label">생성 가능</span> <span class="gen-values">${escPipeline(text)}</span>`;
}

function csvExpandAdded(d) {
    if (typeof d.rows_added === 'number') return d.rows_added;
    return (d.expanded || 0) + (d.expanded_items || 0) + (d.expanded_guides || 0);
}

function remainingText(p) {
    const snap = pipelineBacklogSnap(p);
    const siteId = (p && p.site_id) || '';
    return generatableText(snap, siteId);
}

function nextRunText(snap) {
    const next = snap && snap.next_run;
    if (!next) return '';
    const lim = next.limits || { guide: 3, content: 6 };
    const bits = [];
    if (next.guides_topics) bits.push(`가이드 ${next.guides_topics}`);
    if (next.items_pairs) bits.push(`콘텐츠 ${next.items_pairs}`);
    if (next.korean_files) bits.push(`번역 ${next.korean_files}`);
    if (!bits.length) return '';
    return `다음 실행 ${bits.join(' · ')} (한도 가이드 ${lim.guide} · 콘텐츠 ${lim.content})`;
}

function backlogHtml(p) {
    const snap = pipelineBacklogSnap(p);
    const refreshBtn = (siteId, disabled) =>
        `<button type="button" class="btn btn-ghost btn-sm" onclick="refreshBacklog('${escPipeline(siteId)}')" ${disabled ? 'disabled' : ''}>건수 새로고침</button>`;
    const actions = (r, e) => `<div class="pipe-actions">${r}${e || ''}</div>`;
    if (!snap) {
        return `<div class="dash-pipeline">
            <p class="pipe-summary generatable-summary"><span class="gen-label">생성 가능</span> <span class="gen-values">—</span></p>
            ${actions(refreshBtn(p.site_id, false), '')}
        </div>`;
    }
    const exp = snap.csv_expand || {};
    const expandAvail = csvExpandAvail(snap);
    const expandTitle = expandAvail
        ? `CSV에 ${expandAvail}건 추가 가능 (시드 토픽)`
        : '주간 시드 토픽 추가 (이미 있으면 스킵)';
    const expandBtn = `<button type="button" class="btn btn-ghost btn-sm" onclick="expandCsv('${escPipeline(p.site_id)}')" ${p.running ? 'disabled' : ''} title="${escPipeline(expandTitle)}">CSV 추가${expandAvail ? ` (${expandAvail})` : ''}</button>`;
    return `<div class="dash-pipeline">
        <p class="pipe-summary generatable-summary">${generatableHtml(snap, p.site_id)}</p>
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
    track.style.display = 'flex';
    gen.className = 'phase-step';
    dep.className = 'phase-step';
    if (!running) {
        gen.classList.add('idle');
        dep.classList.add('idle');
        return;
    }
    if (phase === 'deploy') {
        gen.classList.add('done');
        dep.classList.add('active');
    } else {
        gen.classList.add('active');
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
    let html = '';
    if (summary?.created_labels?.length) {
        html += `<li class="created-highlight">+ 추가 ${summary.created_labels.length}건: ${escPipeline(summary.created_labels.join(', '))}</li>`;
    }
    html += lines.map(l => `<li>${escPipeline(l)}</li>`).join('');
    linesEl.innerHTML = html;

    const snip = (summary?.log_snippet || '').trim();
    if (snipEl && logLabel) {
        logLabel.style.display = 'block';
        logLabel.textContent = snip
            ? (phase === 'deploy' && running ? 'deploy.sh 로그 (실시간)' : '파이프라인 로그')
            : '파이프라인 로그';
        snipEl.style.display = 'block';
        snipEl.textContent = snip || '—';
    }

    const fullText = (opts?.deploy_log_tail && running && phase === 'deploy')
        ? opts.deploy_log_tail + '\n\n--- pipeline ---\n\n' + (logTail || '')
        : (logTail || '');
    if (fullWrap && fullPre) {
        fullWrap.style.display = 'block';
        fullPre.textContent = fullText || '—';
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
    if (!backlogBootstrapDone) {
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
    const pipe = typeof pipelineForSite === 'function' ? pipelineForSite(siteId) : null;
    const avail = csvExpandAvail(pipelineBacklogSnap(pipe));
    const msg = avail > 0
        ? `CSV에 시드 토픽 최대 ${avail}건을 추가합니다. 계속할까요?`
        : 'CSV 시드 추가를 시도합니다 (이미 등록된 토픽은 건너뜁니다). 계속할까요?';
    if (!confirm(msg)) return;
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
    const added = csvExpandAdded(d);
    showToast(added > 0 ? `CSV +${added}행 추가됨` : '추가된 행 없음 (시드가 이미 등록됨)');
    await refreshBacklog(siteId, { silent: true });
}
