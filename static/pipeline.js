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

const AI_QUEUE_SITES = new Set([
    'okstats', 'okramen', 'okonsen', 'okcaddie',
    'starful.biz', 'jpcampus', 'krcampus',
]);

const TRENDS_SEED_SITES = new Set([
    'okstats', 'okramen', 'okonsen', 'okcaddie',
    'starful.biz', 'jpcampus', 'krcampus',
]);

function isAiQueueSite(siteId) {
    return AI_QUEUE_SITES.has(siteId);
}

function isTrendsSeedSite(siteId) {
    return TRENDS_SEED_SITES.has(siteId);
}

function aiQueueContentLabel(siteId) {
    if (siteId === 'okstats') return '인사이트';
    if (siteId === 'okramen') return '라멘';
    if (siteId === 'okonsen') return '온천';
    if (siteId === 'okcaddie') return '코스';
    if (siteId === 'starful.biz') return '포지션';
    return '아이템';
}

function aiQueueDefaults(snap) {
    const exp = (snap && snap.csv_expand) || {};
    return {
        content: exp.default_insights ?? exp.default_items ?? exp.default_positions ?? 6,
        guides: exp.default_guides ?? 3,
        schools: exp.default_schools ?? 3,
        universities: exp.default_universities ?? 3,
        mode: exp.queue_mode || '',
    };
}

function aiQueueInputs(siteId, snap, disabled) {
    const defs = aiQueueDefaults(snap);
    const dis = disabled ? 'disabled' : '';
    if (siteId === 'starful.biz') {
        return `<span class="statfacts-queue-inputs">
            <label class="pipe-num-label">포지션
                <input type="number" min="0" max="30" value="${defs.content}" id="aq-content-${escPipeline(siteId)}" class="pipe-num" ${dis}>
            </label>
        </span>`;
    }
    if (siteId === 'jpcampus') {
        return `<span class="statfacts-queue-inputs">
            <label class="pipe-num-label">가이드
                <input type="number" min="0" max="15" value="${defs.guides}" id="aq-guides-${escPipeline(siteId)}" class="pipe-num" ${dis}>
            </label>
            <label class="pipe-num-label">대학
                <input type="number" min="0" max="15" value="${defs.universities}" id="aq-univs-${escPipeline(siteId)}" class="pipe-num" ${dis}>
            </label>
        </span>`;
    }
    if (siteId === 'krcampus') {
        return `<span class="statfacts-queue-inputs">
            <label class="pipe-num-label">가이드
                <input type="number" min="0" max="15" value="${defs.guides}" id="aq-guides-${escPipeline(siteId)}" class="pipe-num" ${dis}>
            </label>
            <label class="pipe-num-label">어학원
                <input type="number" min="0" max="15" value="${defs.schools}" id="aq-schools-${escPipeline(siteId)}" class="pipe-num" ${dis}>
            </label>
            <label class="pipe-num-label">대학
                <input type="number" min="0" max="15" value="${defs.universities}" id="aq-univs-${escPipeline(siteId)}" class="pipe-num" ${dis}>
            </label>
        </span>`;
    }
    const contentLabel = aiQueueContentLabel(siteId);
    return `<span class="statfacts-queue-inputs">
        <label class="pipe-num-label">${escPipeline(contentLabel)}
            <input type="number" min="0" max="30" value="${defs.content}" id="aq-content-${escPipeline(siteId)}" class="pipe-num" ${dis}>
        </label>
        <label class="pipe-num-label">가이드
            <input type="number" min="0" max="15" value="${defs.guides}" id="aq-guides-${escPipeline(siteId)}" class="pipe-num" ${dis}>
        </label>
    </span>`;
}

function readAiQueueCounts(siteId) {
    const defs = aiQueueDefaults(pipelineBacklogSnap(pipelineForSite(siteId)));
    const c = document.getElementById(`aq-content-${siteId}`);
    const g = document.getElementById(`aq-guides-${siteId}`);
    const s = document.getElementById(`aq-schools-${siteId}`);
    const u = document.getElementById(`aq-univs-${siteId}`);
    return {
        insight_count: c ? Math.max(0, parseInt(c.value, 10) || 0) : defs.content,
        guide_count: g ? Math.max(0, parseInt(g.value, 10) || 0) : defs.guides,
        school_count: s ? Math.max(0, parseInt(s.value, 10) || 0) : defs.schools,
        university_count: u ? Math.max(0, parseInt(u.value, 10) || 0) : defs.universities,
    };
}

function aiQueueExpandMessage(siteId, counts) {
    if (siteId === 'starful.biz') {
        return `AI가 포지션 ${counts.insight_count}건을 작성 목록에 추가합니다. 계속할까요?`;
    }
    if (siteId === 'jpcampus') {
        return `AI가 가이드 ${counts.guide_count}건 · 대학 ${counts.university_count}건을 목록에 추가합니다. 계속할까요?`;
    }
    if (siteId === 'krcampus') {
        return `AI가 가이드 ${counts.guide_count}건 · 어학원 ${counts.school_count}건 · 대학 ${counts.university_count}건을 목록에 추가합니다. 계속할까요?`;
    }
    const contentLabel = aiQueueContentLabel(siteId);
    return `AI가 ${contentLabel} ${counts.insight_count}건 · 가이드 ${counts.guide_count}건을 작성 목록에 추가합니다. 계속할까요?`;
}

function aiQueueBusySub(siteId, counts) {
    if (siteId === 'starful.biz') {
        return `포지션 ${counts.insight_count}건 · 보통 10~30초`;
    }
    if (siteId === 'jpcampus') {
        return `가이드 ${counts.guide_count} · 대학 ${counts.university_count} · 보통 10~30초`;
    }
    if (siteId === 'krcampus') {
        return `가이드 ${counts.guide_count} · 어학원 ${counts.school_count} · 대학 ${counts.university_count} · 보통 10~30초`;
    }
    const contentLabel = aiQueueContentLabel(siteId);
    return `${contentLabel} ${counts.insight_count}건 · 가이드 ${counts.guide_count}건 · 보통 10~30초`;
}

function aiQueueCountValid(siteId, counts) {
    if (siteId === 'starful.biz') return counts.insight_count > 0;
    if (siteId === 'jpcampus') {
        return counts.guide_count > 0 || counts.university_count > 0;
    }
    if (siteId === 'krcampus') {
        return counts.guide_count > 0 || counts.school_count > 0 || counts.university_count > 0;
    }
    return counts.insight_count > 0 || counts.guide_count > 0;
}

function aiQueueCountError(siteId) {
    if (siteId === 'starful.biz') return '포지션 개수를 1 이상 입력하세요';
    if (siteId === 'jpcampus') return '가이드·대학 중 1개 이상 입력하세요';
    if (siteId === 'krcampus') return '가이드·어학원·대학 중 1개 이상 입력하세요';
    return `${aiQueueContentLabel(siteId)} 또는 가이드 개수를 1 이상 입력하세요`;
}

function aiQueueExpandBody(siteId, counts) {
    const body = { site_id: siteId };
    if (siteId === 'starful.biz') {
        body.insight_count = counts.insight_count;
        return JSON.stringify(body);
    }
    if (siteId === 'jpcampus') {
        body.guide_count = counts.guide_count;
        body.university_count = counts.university_count;
        return JSON.stringify(body);
    }
    if (siteId === 'krcampus') {
        body.guide_count = counts.guide_count;
        body.school_count = counts.school_count;
        body.university_count = counts.university_count;
        return JSON.stringify(body);
    }
    body.insight_count = counts.insight_count;
    body.guide_count = counts.guide_count;
    return JSON.stringify(body);
}

function aiQueueRunBody(siteId) {
    const counts = readAiQueueCounts(siteId);
    if (!aiQueueCountValid(siteId, counts)) return null;
    return aiQueueExpandBody(siteId, counts);
}

function statfactsQueueInputs(siteId, snap, disabled) {
    return aiQueueInputs(siteId, snap, disabled);
}

function readStatfactsQueueCounts(siteId) {
    return readAiQueueCounts(siteId);
}

function statfactsDefaultCounts(snap) {
    const d = aiQueueDefaults(snap);
    return { insights: d.content, guides: d.guides };
}

function mdPendingText(snap, siteId) {
    if (!snap) return '—';
    const g = snap.generatable || {};
    const csv = snap.csv || {};
    const pending = (n, total) => (total != null && total !== '' ? `${n}/${total}` : `${n}`);

    const content = g.content || 0;
    const guides = g.guides || 0;
    const csvItems = csv.items;
    const csvGuides = csv.guides;

    if (siteId === 'okstats') {
        const total = content + guides;
        return `${total}건 (인사이트 ${content} · 가이드 ${guides})`;
    }
    if (siteId === 'okramen' || siteId === 'okonsen' || siteId === 'okcaddie') {
        const total = content + guides;
        const itemLabel = aiQueueContentLabel(siteId);
        return `${total}건 (${itemLabel} ${content} · 가이드 ${guides})`;
    }
    if (siteId === 'starful.biz') {
        return `${guides}건 (포지션 ${guides})`;
    }
    if (siteId === 'jpcampus') {
        const univs = g.univs || 0;
        const total = guides + univs;
        return `${total}건 (가이드 ${guides} · 대학 ${univs})`;
    }
    if (siteId === 'krcampus') {
        const schools = g.schools || 0;
        const univs = g.univs || 0;
        const total = guides + schools + univs;
        return `${total}건 (가이드 ${guides} · 어학원 ${schools} · 대학 ${univs})`;
    }
    return `콘텐츠 ${pending(content, csvItems)} · 가이드 ${pending(guides, csvGuides)}`;
}

function generatableText(snap, siteId) {
    return mdPendingText(snap, siteId);
}

function mdPendingHtml(snap, siteId) {
    const text = mdPendingText(snap, siteId);
    const label = isAiQueueSite(siteId)
        ? '생성 가능'
        : 'MD 대기';
    const title = isAiQueueSite(siteId)
        ? '목록에 있고 MD가 아직 없는 건수'
        : 'CSV에 있지만 MD가 아직 없는 건수 (앞=대기, 뒤=CSV 전체)';
    return `<span class="gen-label" title="${escPipeline(title)}">${label}</span> <span class="gen-values">${escPipeline(text)}</span>`;
}

function generatableHtml(snap, siteId) {
    return mdPendingHtml(snap, siteId);
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
    let expandBtn = '';
    if (isAiQueueSite(p.site_id)) {
        const contentLabel = aiQueueContentLabel(p.site_id);
        expandBtn = `${aiQueueInputs(p.site_id, snap, p.running)}
            <button type="button" class="btn btn-ghost btn-sm" onclick="expandCsv('${escPipeline(p.site_id)}')" ${p.running ? 'disabled' : ''} title="AI가 ${escPipeline(contentLabel)}·가이드 주제를 목록에 추가">목록 추가</button>`;
        if (isTrendsSeedSite(p.site_id)) {
            expandBtn += ` <button type="button" class="btn btn-ghost btn-sm" onclick="seedTrends('${escPipeline(p.site_id)}')" ${p.running ? 'disabled' : ''} title="Google Trends 급상승·관련 검색어를 가이드/포지션 목록에 추가 (Hatena 제외)">Trends</button>`;
        }
    } else {
        const expandTitle = expandAvail
            ? `CSV에 ${expandAvail}건 추가 가능 (시드 토픽)`
            : '주간 시드 토픽 추가 (이미 있으면 스킵)';
        expandBtn = `<button type="button" class="btn btn-ghost btn-sm" onclick="expandCsv('${escPipeline(p.site_id)}')" ${p.running ? 'disabled' : ''} title="${escPipeline(expandTitle)}">CSV 추가${expandAvail ? ` (${expandAvail})` : ''}</button>`;
    }
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
    const phase = opts?.phase || null;
    const running = !!opts?.running;
    const pipe = typeof pipelineForSite === 'function' ? pipelineForSite(activePipelineSite) : null;
    const siteLabel = opts?.siteLabel || pipe?.label || activePipelineSite || '';
    if (typeof pipelineStatusView === 'function' && typeof hubOpenProgress === 'function') {
        const view = pipelineStatusView(summary, logTail, { ...opts, siteLabel });
        if (view.running) {
            if (!hubModalBusy) hubOpenProgress(view.title, view.meta || siteLabel);
            else hubUpdateProgress(view);
        } else if (hubModalBusy) {
            hubOpenResult(view);
        }
    }

    const linesEl = document.getElementById('summary-lines');
    const logLabel = document.getElementById('log-label');
    const fullPre = document.getElementById('log-full-text');
    const siteEl = document.getElementById('result-site');
    if (!linesEl) return;

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

    const fullText = (opts?.deploy_log_tail && running && phase === 'deploy')
        ? opts.deploy_log_tail + '\n\n--- pipeline ---\n\n' + (logTail || '')
        : (logTail || '');
    if (fullPre) {
        if (logLabel) {
            logLabel.style.display = 'block';
            logLabel.textContent = running && phase === 'deploy' ? '상세 로그 (deploy + pipeline)' : '상세 로그';
        }
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
    if (isAiQueueSite(siteId)) {
        const counts = readAiQueueCounts(siteId);
        if (!aiQueueCountValid(siteId, counts)) {
            showToast(aiQueueCountError(siteId));
            return;
        }
    }
    const siteLabel = label || siteId;
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress('① 생성·빌드 중…', siteLabel + ' · 시작 요청 중…');
    }
    setResultBadge('run', '시작');
    renderSummary(
        { title: '생성 중', lines: ['① 콘텐츠 생성을 시작합니다…'] },
        '',
        null,
        { running: true, phase: 'generate', siteLabel }
    );

    const body = isAiQueueSite(siteId)
        ? aiQueueRunBody(siteId)
        : JSON.stringify({ site_id: siteId });
    const res = await fetch('/api/content/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
    });
    const d = await res.json();
    if (!res.ok) {
        setResultBadge('err', '오류');
        renderSummary(
            { title: '실패', lines: [d.error || '시작 실패'] },
            '',
            null,
            { siteLabel }
        );
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
    const pipe = pipelineForSite(siteId);
    const siteLabel = pipe?.label || siteId;
    const res = await fetch('/api/content/pipeline/result?site_id=' + encodeURIComponent(siteId));
    const d = await res.json();
    renderSummary(d.summary, d.log_tail || '', {
        last_run_display: d.last_run_display,
        last_run_ok: d.last_run_ok,
    }, {
        running: d.running,
        phase: d.phase,
        deploy_log_tail: d.deploy_log_tail,
        siteLabel,
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
    if (typeof loadAiSpend === 'function') loadAiSpend();
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
    let body;
    let busyMsg = 'CSV 시드 추가 중…';
    let busySub = '잠시만 기다려 주세요';
    if (isAiQueueSite(siteId)) {
        const counts = readAiQueueCounts(siteId);
        if (!aiQueueCountValid(siteId, counts)) {
            showToast(aiQueueCountError(siteId));
            return;
        }
        if (!confirm(aiQueueExpandMessage(siteId, counts))) return;
        body = aiQueueExpandBody(siteId, counts);
        busyMsg = `AI 목록 생성 중…`;
        busySub = aiQueueBusySub(siteId, counts);
    } else {
        const avail = csvExpandAvail(pipelineBacklogSnap(pipe));
        const msg = avail > 0
            ? `CSV에 시드 토픽 최대 ${avail}건을 추가합니다. 계속할까요?`
            : 'CSV 시드 추가를 시도합니다 (이미 등록된 토픽은 건너뜁니다). 계속할까요?';
        if (!confirm(msg)) return;
        body = JSON.stringify({ site_id: siteId });
    }
    if (typeof hubOpenProgress === 'function') hubOpenProgress(busyMsg, busySub);
    let d = {};
    try {
        const res = await fetch('/api/content/pipeline/csv-expand', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        });
        d = await res.json();
        if (!res.ok) {
            const err = d.error || '목록 추가 실패';
            showToast(err);
            if (typeof hubOpenResult === 'function') {
                hubOpenResult({
                    title: '목록 추가 실패',
                    meta: siteId,
                    lines: [err],
                    state: 'failed',
                    error: err,
                });
            }
            return;
        }
        const added = csvExpandAdded(d);
        const lines = [];
        if (added > 0) lines.push(`목록 +${added}건 추가됨`);
        if (d.expanded_items) lines.push(`아이템 +${d.expanded_items}`);
        if (d.expanded_guides) lines.push(`가이드 +${d.expanded_guides}`);
        if (!lines.length) lines.push(d.error || d.message || '추가된 행 없음');
        showToast(added > 0 ? `목록 +${added}건 추가됨` : (d.error || '추가된 행 없음'));
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: added > 0 ? '목록 추가 완료' : '목록 추가',
                meta: siteId,
                lines,
                state: added > 0 ? 'success' : 'idle',
            });
        }
        await refreshBacklog(siteId, { silent: true });
    } catch (_) {
        showToast('목록 추가 요청 실패');
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: '목록 추가 실패',
                meta: siteId,
                lines: ['요청 실패'],
                state: 'failed',
                error: '요청 실패',
            });
        }
    }
}

async function seedTrends(siteId) {
    if (!isTrendsSeedSite(siteId)) {
        showToast('Trends 시드 미지원 사이트');
        return;
    }
    if (!confirm(`Google Trends 급상승·관련 검색어로 ${siteId} 토픽 목록을 추가합니다.\n(가이드/포지션만 · 최대 8건 · Hatena 제외)`)) {
        return;
    }
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress('Trends 시드 중…', 'Google Trends 조회 후 목록에 추가합니다');
    }
    let d = {};
    try {
        const res = await fetch('/api/content/pipeline/trends-seed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ site_id: siteId, limit: 8 }),
        });
        d = await res.json();
        if (!res.ok) {
            const err = d.error || 'Trends 시드 실패';
            showToast(err);
            if (typeof hubOpenResult === 'function') {
                hubOpenResult({
                    title: 'Trends 시드 실패',
                    meta: siteId,
                    lines: [err],
                    state: 'failed',
                    error: err,
                });
            }
            return;
        }
        const added = typeof d.rows_added === 'number' ? d.rows_added : 0;
        const lines = [];
        if (d.queries_found) lines.push(`Trends 후보 ${d.queries_found}건`);
        if (added > 0) lines.push(`목록 +${added}건 추가`);
        (d.sample_queries || []).slice(0, 5).forEach((q) => lines.push(`· ${q}`));
        if (!lines.length) lines.push('추가된 행 없음');
        showToast(added > 0 ? `Trends +${added}건` : 'Trends 추가 없음');
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: added > 0 ? 'Trends 시드 완료' : 'Trends 시드',
                meta: siteId,
                lines,
                state: added > 0 ? 'success' : 'idle',
            });
        }
        await refreshBacklog(siteId, { silent: true });
    } catch (_) {
        showToast('Trends 시드 요청 실패');
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: 'Trends 시드 실패',
                meta: siteId,
                lines: ['요청 실패'],
                state: 'failed',
                error: '요청 실패',
            });
        }
    }
}
