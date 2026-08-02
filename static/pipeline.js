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
    'okramen', 'okonsen', 'okcaddie',
    'starful.biz', 'jpcampus', 'krcampus', 'okpy',
]);

const TRENDS_SEED_SITES = new Set([
    'okramen', 'okonsen', 'okcaddie',
    'starful.biz', 'jpcampus', 'krcampus', 'okpy',
]);

function isAiQueueSite(siteId) {
    return AI_QUEUE_SITES.has(siteId);
}

function isTrendsSeedSite(siteId) {
    return TRENDS_SEED_SITES.has(siteId);
}

/** TourAPI 등 — CSV/AI 목록 추가 없음 */
function supportsTopicExpand(siteId) {
    return siteId !== 'krcare';
}

function aiQueueContentLabel(siteId) {
    if (siteId === 'statfacts') return '인사이트';
    if (siteId === 'okramen') return '라멘';
    if (siteId === 'okonsen') return '온천';
    if (siteId === 'okcaddie') return '코스';
    if (siteId === 'starful.biz') return '포지션';
    if (siteId === 'okpy') return 'Python';
    return '아이템';
}

window.__aqCounts = window.__aqCounts || {};

function aiQueueDefaults(snap) {
    const exp = (snap && snap.csv_expand) || {};
    return {
        content: exp.default_insights ?? exp.default_items ?? exp.default_positions ?? 3,
        guides: exp.default_guides ?? 2,
        schools: exp.default_schools ?? 2,
        universities: exp.default_universities ?? 2,
        mode: exp.queue_mode || '',
    };
}

function aqClamp(n, max) {
    const v = Number.isFinite(n) ? Math.trunc(n) : 0;
    return Math.max(0, Math.min(max, v));
}

function aqParseInput(el, max) {
    if (!el) return 0;
    const raw = String(el.value || '').trim();
    if (raw === '') return 0;
    return aqClamp(parseInt(raw, 10), max);
}

function resolvedAqDefs(siteId, snap) {
    const defs = aiQueueDefaults(snap);
    const saved = window.__aqCounts[siteId];
    if (!saved) return defs;
    return {
        content: saved.content != null ? saved.content : defs.content,
        guides: saved.guides != null ? saved.guides : defs.guides,
        schools: saved.schools != null ? saved.schools : defs.schools,
        universities: saved.universities != null ? saved.universities : defs.universities,
        mode: defs.mode,
    };
}

function persistAqCounts(siteId, counts) {
    window.__aqCounts[siteId] = {
        content: counts.insight_count,
        guides: counts.guide_count,
        schools: counts.school_count,
        universities: counts.university_count,
    };
}

function saveAqCountsFromDom(siteId) {
    if (!siteId) return;
    const c = document.getElementById(`aq-content-${siteId}`);
    const g = document.getElementById(`aq-guides-${siteId}`);
    const s = document.getElementById(`aq-schools-${siteId}`);
    const u = document.getElementById(`aq-univs-${siteId}`);
    if (!c && !g && !s && !u) return;
    persistAqCounts(siteId, {
        insight_count: aqParseInput(c, 30),
        guide_count: aqParseInput(g, 15),
        school_count: aqParseInput(s, 15),
        university_count: aqParseInput(u, 15),
    });
}

function aqStepperField(label, id, value, max, disabled) {
    const dis = disabled ? 'disabled' : '';
    return `<label class="pipe-num-label">${escPipeline(label)}
        <span class="pipe-stepper">
            <button type="button" class="pipe-step" data-aq-for="${escPipeline(id)}" data-aq-delta="-1" data-aq-max="${max}" ${dis} aria-label="감소">−</button>
            <input type="text" inputmode="numeric" pattern="[0-9]*" autocomplete="off"
                id="${escPipeline(id)}" class="pipe-num" value="${value}" data-aq-max="${max}" ${dis}
                title="주제 건수 (0=해당 단계 건너뜀)">
            <button type="button" class="pipe-step" data-aq-for="${escPipeline(id)}" data-aq-delta="1" data-aq-max="${max}" ${dis} aria-label="증가">+</button>
        </span>
    </label>`;
}

function aiQueueInputs(siteId, snap, disabled) {
    const defs = resolvedAqDefs(siteId, snap);
    if (siteId === 'starful.biz') {
        return `<span class="statfacts-queue-inputs" data-aq-site="${escPipeline(siteId)}">
            ${aqStepperField('포지션', `aq-content-${siteId}`, defs.content, 30, disabled)}
        </span>`;
    }
    if (siteId === 'jpcampus') {
        return `<span class="statfacts-queue-inputs" data-aq-site="${escPipeline(siteId)}">
            ${aqStepperField('가이드', `aq-guides-${siteId}`, defs.guides, 15, disabled)}
            ${aqStepperField('대학', `aq-univs-${siteId}`, defs.universities, 15, disabled)}
        </span>`;
    }
    if (siteId === 'krcampus') {
        return `<span class="statfacts-queue-inputs" data-aq-site="${escPipeline(siteId)}">
            ${aqStepperField('가이드', `aq-guides-${siteId}`, defs.guides, 15, disabled)}
            ${aqStepperField('어학원', `aq-schools-${siteId}`, defs.schools, 15, disabled)}
            ${aqStepperField('대학', `aq-univs-${siteId}`, defs.universities, 15, disabled)}
        </span>`;
    }
    if (siteId === 'okpy') {
        return `<span class="statfacts-queue-inputs" data-aq-site="${escPipeline(siteId)}">
            ${aqStepperField('Python', `aq-content-${siteId}`, defs.content, 15, disabled)}
            ${aqStepperField('Cloud', `aq-schools-${siteId}`, defs.schools, 15, disabled)}
            ${aqStepperField('Terraform', `aq-univs-${siteId}`, defs.universities, 15, disabled)}
            ${aqStepperField('Data JA', `aq-guides-${siteId}`, defs.guides, 15, disabled)}
        </span>`;
    }
    const contentLabel = aiQueueContentLabel(siteId);
    return `<span class="statfacts-queue-inputs" data-aq-site="${escPipeline(siteId)}" title="입력한 주제 수만큼 생성 (en+ko는 파일 2개=주제 1건)">
        ${aqStepperField(contentLabel, `aq-content-${siteId}`, defs.content, 30, disabled)}
        ${aqStepperField('가이드', `aq-guides-${siteId}`, defs.guides, 15, disabled)}
    </span>`;
}

function readAiQueueCounts(siteId) {
    const defs = resolvedAqDefs(siteId, pipelineBacklogSnap(pipelineForSite(siteId)));
    const c = document.getElementById(`aq-content-${siteId}`);
    const g = document.getElementById(`aq-guides-${siteId}`);
    const s = document.getElementById(`aq-schools-${siteId}`);
    const u = document.getElementById(`aq-univs-${siteId}`);
    const counts = {
        insight_count: c ? aqParseInput(c, 30) : defs.content,
        guide_count: g ? aqParseInput(g, 15) : defs.guides,
        school_count: s ? aqParseInput(s, 15) : defs.schools,
        university_count: u ? aqParseInput(u, 15) : defs.universities,
    };
    persistAqCounts(siteId, counts);
    return counts;
}

function bindAqSteppers(root) {
    const scope = root || document;
    scope.querySelectorAll('.statfacts-queue-inputs').forEach((wrap) => {
        if (wrap.dataset.aqBound === '1') return;
        wrap.dataset.aqBound = '1';
        wrap.addEventListener('click', (ev) => {
            const btn = ev.target.closest('.pipe-step');
            if (!btn || btn.disabled) return;
            const id = btn.getAttribute('data-aq-for');
            const input = id ? document.getElementById(id) : null;
            if (!input || input.disabled) return;
            const max = parseInt(btn.getAttribute('data-aq-max') || input.dataset.aqMax || '30', 10);
            const delta = parseInt(btn.getAttribute('data-aq-delta') || '0', 10);
            input.value = String(aqClamp(aqParseInput(input, max) + delta, max));
            const siteId = wrap.getAttribute('data-aq-site');
            if (siteId) saveAqCountsFromDom(siteId);
        });
        wrap.addEventListener('change', (ev) => {
            const input = ev.target.closest('.pipe-num');
            if (!input) return;
            const max = parseInt(input.dataset.aqMax || '30', 10);
            input.value = String(aqParseInput(input, max));
            const siteId = wrap.getAttribute('data-aq-site');
            if (siteId) saveAqCountsFromDom(siteId);
        });
        wrap.addEventListener('keydown', (ev) => {
            const input = ev.target.closest('.pipe-num');
            if (!input) return;
            if (!/^[0-9]$/.test(ev.key) && !['Backspace', 'Delete', 'Tab', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'Enter'].includes(ev.key) && !ev.metaKey && !ev.ctrlKey) {
                ev.preventDefault();
            }
        });
    });
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
    if (siteId === 'okpy') {
        return `AI가 Python ${counts.insight_count} · Cloud ${counts.school_count} · Terraform ${counts.university_count} · Data JA ${counts.guide_count}건을 목록에 추가합니다. 계속할까요?`;
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
    if (siteId === 'okpy') {
        return `Python ${counts.insight_count} · Cloud ${counts.school_count} · Terraform ${counts.university_count} · Data JA ${counts.guide_count} · 보통 10~30초`;
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
    if (siteId === 'okpy') {
        return counts.insight_count > 0 || counts.school_count > 0 || counts.university_count > 0 || counts.guide_count > 0;
    }
    return counts.insight_count > 0 || counts.guide_count > 0;
}

function aiQueueCountError(siteId) {
    if (siteId === 'starful.biz') return '포지션 개수를 1 이상 입력하세요';
    if (siteId === 'jpcampus') return '가이드·대학 중 1개 이상 입력하세요';
    if (siteId === 'krcampus') return '가이드·어학원·대학 중 1개 이상 입력하세요';
    if (siteId === 'okpy') return 'Python·Cloud·Terraform·Data JA 중 1개 이상 입력하세요';
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
    if (siteId === 'okpy') {
        body.insight_count = counts.insight_count;
        body.school_count = counts.school_count;
        body.university_count = counts.university_count;
        body.guide_count = counts.guide_count;
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

    if (siteId === 'statfacts') {
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
    if (siteId === 'okpy') {
        const py = g.python != null ? g.python : (snap.backlog && snap.backlog.python_pending) || 0;
        const cloud = g.cloud != null ? g.cloud : (snap.backlog && snap.backlog.cloud_pending) || 0;
        const tf = g.terraform != null ? g.terraform : (snap.backlog && snap.backlog.terraform_pending) || 0;
        const ja = g.data_analysis_ja != null ? g.data_analysis_ja : (snap.backlog && snap.backlog.data_analysis_ja_pending) || 0;
        const total = py + cloud + tf + ja;
        const csvPy = csv.python;
        const csvCloud = csv.cloud;
        const csvTf = csv.terraform;
        return `${total}건 (Python ${pending(py, csvPy)} · Cloud ${pending(cloud, csvCloud)} · Terraform ${pending(tf, csvTf)} · Data JA ${ja})`;
    }
    if (siteId === 'krcare') {
        return 'TourAPI 수집';
    }
    return `콘텐츠 ${pending(content, csvItems)} · 가이드 ${pending(guides, csvGuides)}`;
}

function generatableText(snap, siteId) {
    return mdPendingText(snap, siteId);
}

function mdPendingHtml(snap, siteId) {
    const text = mdPendingText(snap, siteId);
    if (siteId === 'krcare') {
        return `<span class="gen-label" title="TourAPI MdclTursm 클리닉 수집 · 목록 추가 없음">갱신</span> <span class="gen-values">${escPipeline(text)}</span>`;
    }
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
    const lim = next.limits || { guide: 2, content: 3 };
    const bits = [];
    if (next.guides_topics) bits.push(`가이드 ${next.guides_topics}`);
    if (next.items_pairs) bits.push(`콘텐츠 ${next.items_pairs}`);
    if (next.korean_files) bits.push(`번역 ${next.korean_files}`);
    if (!bits.length) return '';
    return `다음 실행 후보 ${bits.join(' · ')} (기본 한도 가이드 ${lim.guide} · 콘텐츠 ${lim.content}; 실행 시 입력값 우선)`;
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
    if (supportsTopicExpand(p.site_id)) {
        if (isAiQueueSite(p.site_id)) {
            const contentLabel = aiQueueContentLabel(p.site_id);
            expandBtn = `${aiQueueInputs(p.site_id, snap, p.running)}
                <button type="button" class="btn btn-ghost btn-sm" onclick="expandCsv('${escPipeline(p.site_id)}')" ${p.running ? 'disabled' : ''} title="AI가 ${escPipeline(contentLabel)}·가이드 주제를 목록에 추가">목록 추가</button>`;
        } else {
            const expandTitle = expandAvail
                ? `CSV에 ${expandAvail}건 추가 가능 (시드 토픽)`
                : '주간 시드 토픽 추가 (이미 있으면 스킵)';
            expandBtn = `<button type="button" class="btn btn-ghost btn-sm" onclick="expandCsv('${escPipeline(p.site_id)}')" ${p.running ? 'disabled' : ''} title="${escPipeline(expandTitle)}">CSV 추가${expandAvail ? ` (${expandAvail})` : ''}</button>`;
        }
    }
    let stayBtn = '';
    if (p.site_id === 'jpcampus') {
        stayBtn = ` <button type="button" class="btn btn-ghost btn-sm" onclick="openStayPublishPanel()" ${p.running ? 'disabled' : ''} title="숙소 카탈로그에서 선택 발행">숙소 발행</button>`;
    }
    return `<div class="dash-pipeline">
        <p class="pipe-summary generatable-summary">${generatableHtml(snap, p.site_id)}</p>
        ${actions(refreshBtn(p.site_id, p.running), expandBtn + stayBtn)}
    </div>`;
}

function pipelineActionsHtml(p) {
    if (!p) return '';
    const cls = p.running ? 'running' : '';
    const deployBusy = typeof hubSiteHasDeployJob === 'function' && hubSiteHasDeployJob(p.site_id);
    const canRun = p.available && !p.running && !deployBusy;
    return `<div class="dash-pipeline-wrap ${cls}" data-pipeline-site="${escPipeline(p.site_id)}">
        ${backlogHtml(p)}
        <button type="button" class="btn btn-primary pipe-run" ${canRun ? '' : 'disabled'}
            title="${deployBusy ? '배포 진행 중' : ''}"
            onclick="runPipeline('${escPipeline(p.site_id)}', '${escPipeline(p.label)}')">
            ${p.running
                ? (p.phase === 'images' ? '⑥ 이미지…' : '① 생성 중…')
                : (deployBusy ? '배포 중…'
                    : (p.site_id === 'krcare' ? 'TourAPI 갱신' : '콘텐츠 생성'))}
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
    if (!track || !gen) return;
    track.style.display = 'flex';
    gen.className = 'phase-step';
    if (!running) {
        gen.classList.add('idle');
        return;
    }
    if (phase === 'images') {
        gen.textContent = '⑥ 이미지';
        gen.classList.add('active');
    } else {
        gen.textContent = '① 생성·빌드';
        gen.classList.add('active');
    }
}

function renderSummary(summary, logTail, lastRun, opts) {
    const phase = opts?.phase || null;
    const running = !!opts?.running;
    const pipe = typeof pipelineForSite === 'function' ? pipelineForSite(activePipelineSite) : null;
    const siteId = opts?.siteId || pipe?.site_id || activePipelineSite || '';
    const siteLabel = opts?.siteLabel || pipe?.label || activePipelineSite || '';
    if (typeof pipelineStatusView === 'function' && typeof hubOpenProgress === 'function') {
        const view = pipelineStatusView(summary, logTail, { ...opts, siteLabel, siteId });
        const owns = typeof hubModalOwnsSite === 'function'
            ? hubModalOwnsSite(siteId)
            : !!hubModalBusy;
        if (view.running) {
            if (!hubModalBusy || owns) {
                if (!hubModalBusy) {
                    hubOpenProgress(view.title, view.meta || siteLabel, {
                        siteId, siteLabel, kind: 'content',
                    });
                }
                hubUpdateProgress(view);
            } else {
                hubUpdateProgress(view); // dock-only path inside hub_modal
            }
        } else if (owns) {
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
    else if (title === '생성 중') setResultBadge('run', '① 생성·빌드');
    else if (title === '이미지 처리 중') setResultBadge('run', '⑥ 이미지');
    else if (title === '실행 중') setResultBadge('run', '실행 중');
    else setResultBadge('idle', title);

    const lines = summary?.lines?.length ? summary.lines : ['결과 없음'];
    let html = '';
    if (summary?.created_labels?.length) {
        html += `<li class="created-highlight">+ 추가 ${summary.created_labels.length}건: ${escPipeline(summary.created_labels.join(', '))}</li>`;
    }
    html += lines.map(l => `<li>${escPipeline(l)}</li>`).join('');
    linesEl.innerHTML = html;

    const fullText = logTail || '';
    if (fullPre) {
        if (logLabel) {
            logLabel.style.display = 'block';
            logLabel.textContent = running && phase === 'images'
                ? '상세 로그 (이미지)'
                : '상세 로그';
        }
        fullPre.textContent = fullText || '—';
        if (typeof hubStickLogBottom === 'function') hubStickLogBottom(fullPre);
        else {
            fullPre.scrollTop = fullPre.scrollHeight;
            requestAnimationFrame(() => { fullPre.scrollTop = fullPre.scrollHeight; });
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
    if (typeof hubSiteHasDeployJob === 'function' && hubSiteHasDeployJob(siteId)) {
        showToast('배포가 진행 중입니다. 끝난 뒤 콘텐츠를 생성하세요');
        return;
    }
    if (isAiQueueSite(siteId)) {
        const counts = readAiQueueCounts(siteId);
        if (!aiQueueCountValid(siteId, counts)) {
            showToast(aiQueueCountError(siteId));
            return;
        }
    }
    const siteLabel = label || siteId;
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress('① 생성·빌드 중…', siteLabel + ' · 시작 요청 중…', {
            siteId, siteLabel, kind: 'content',
        });
    }
    setResultBadge('run', '시작');
    renderSummary(
        { title: '생성 중', lines: ['① 콘텐츠 생성을 시작합니다…'] },
        '',
        null,
        { running: true, phase: 'generate', siteLabel, siteId }
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
            { siteLabel, siteId }
        );
        if (typeof showToast === 'function') showToast(d.error || '시작 실패');
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
    if (!supportsTopicExpand(siteId)) {
        showToast('이 사이트는 목록 추가가 없습니다 · TourAPI 갱신을 사용하세요');
        return;
    }
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
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress(busyMsg, busySub, { siteId, kind: 'content' });
    }
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
                    siteId,
                    kind: 'content',
                });
            }
            return;
        }
        const added = csvExpandAdded(d);
        const lines = [];
        if (added > 0) lines.push(`목록 +${added}건 추가됨`);
        if (d.expanded_items) lines.push(`아이템 +${d.expanded_items}`);
        if (d.expanded_guides) lines.push(`가이드 +${d.expanded_guides}`);
        if (Array.isArray(d.messages) && d.messages.length) {
            for (const m of d.messages) {
                if (m && !lines.includes(m)) lines.push(m);
            }
        }
        if (!lines.length) lines.push(d.error || d.message || '추가된 행 없음');
        showToast(added > 0 ? `목록 +${added}건 추가됨` : (d.error || '추가된 행 없음'));
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: added > 0 ? '목록 추가 완료' : '목록 추가',
                meta: siteId,
                lines,
                state: added > 0 ? 'success' : 'idle',
                siteId,
                kind: 'content',
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
                siteId,
                kind: 'content',
            });
        }
    }
}

async function seedTrends(siteId) {
    if (!isTrendsSeedSite(siteId)) {
        showToast('Trends 시드 미지원 사이트');
        return;
    }
    if (!confirm(`Google Trends 급상승·관련 검색어로 ${siteId} 토픽 목록을 추가합니다.\n(가이드/포지션/포스트 · 최대 8건)`)) {
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

/* —— JP Campus stay selective publish —— */
async function openStayPublishPanel() {
    let summary = {};
    try {
        const res = await fetch('/api/content/stays/summary');
        summary = await res.json();
        if (summary.error) throw new Error(summary.error);
    } catch (e) {
        showToast('숙소 카탈로그 로드 실패');
        return;
    }
    const regions = Object.keys(summary.regions || {});
    const regionOpts = ['<option value=\"\">전체 지역</option>']
        .concat(regions.map((r) => {
            const b = summary.regions[r] || {};
            return `<option value=\"${escPipeline(r)}\">${escPipeline(r)} (미발행 ${b.unpublished || 0})</option>`;
        }))
        .join('');

    const html = `
        <div class="stay-publish-panel" style="text-align:left;max-width:720px;margin:0 auto">
            <p style="margin:0 0 8px;opacity:.85">카탈로그 ${summary.total || 0} · 발행 ${summary.published || 0} · 미발행 ${summary.unpublished || 0}</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;align-items:center">
                <select id="stay-region" class="pipe-num" style="min-width:140px">${regionOpts}</select>
                <input id="stay-q" type="search" placeholder="검색 (이름/id)" class="pipe-num" style="min-width:160px">
                <button type="button" class="btn btn-ghost btn-sm" onclick="loadStayCatalog()">불러오기</button>
                <button type="button" class="btn btn-primary btn-sm" onclick="publishSelectedStays()">선택 발행</button>
                <button type="button" class="btn btn-ghost btn-sm" onclick="publishStaySample()">지역별 샘플 8</button>
            </div>
            <div id="stay-catalog-list" style="max-height:360px;overflow:auto;border:1px solid rgba(127,127,127,.25);border-radius:8px;padding:8px">불러오기 버튼을 눌러 목록을 확인하세요.</div>
        </div>`;

    if (typeof hubOpenResult === 'function') {
        hubOpenResult({
            title: '숙소 선택 발행',
            meta: 'JP Campus',
            lines: [],
            state: 'idle',
            html,
        });
    } else {
        showToast('숙소 패널을 열 수 없습니다');
        return;
    }
    // Auto-load first page
    setTimeout(() => loadStayCatalog(), 50);
}

async function loadStayCatalog() {
    const region = document.getElementById('stay-region')?.value || '';
    const q = document.getElementById('stay-q')?.value || '';
    const box = document.getElementById('stay-catalog-list');
    if (!box) return;
    box.textContent = '로딩…';
    const params = new URLSearchParams({ unpublished_only: '1', limit: '80' });
    if (region) params.set('region', region);
    if (q) params.set('q', q);
    try {
        const res = await fetch('/api/content/stays/catalog?' + params.toString());
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        const items = data.items || [];
        if (!items.length) {
            box.textContent = '미발행 숙소가 없습니다.';
            return;
        }
        box.innerHTML = items.map((it) => `
            <label style="display:flex;gap:8px;align-items:flex-start;padding:6px 4px;border-bottom:1px solid rgba(127,127,127,.12)">
                <input type="checkbox" class="stay-pick" value="${escPipeline(it.id)}" style="margin-top:3px">
                <span style="flex:1">
                    <strong>${escPipeline(it.name_kr || it.name_en || it.id)}</strong>
                    <span style="opacity:.7"> · ${escPipeline(it.region)} · ${escPipeline(it.operator || '')}</span><br>
                    <small style="opacity:.75">${escPipeline(it.address_kr || it.address_en || '')}</small>
                    <div style="opacity:.55;font-size:12px">${escPipeline(it.id)}</div>
                </span>
            </label>`).join('');
    } catch (e) {
        box.textContent = '로드 실패: ' + (e.message || e);
    }
}

function selectedStayIds() {
    return Array.from(document.querySelectorAll('.stay-pick:checked')).map((el) => el.value);
}

async function publishSelectedStays() {
    const ids = selectedStayIds();
    if (!ids.length) {
        showToast('발행할 숙소를 선택하세요');
        return;
    }
    if (!confirm(`${ids.length}건을 발행할까요? (md 생성 + build)`)) return;
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress('숙소 발행 중…', `${ids.length}건`);
    }
    try {
        const res = await fetch('/api/content/stays/publish', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids, build: true }),
        });
        const data = await res.json();
        const lines = [];
        if (data.summary) {
            lines.push(`발행 ${data.summary.published} / 전체 ${data.summary.total}`);
        }
        if (data.stdout) lines.push(...String(data.stdout).trim().split('\n').slice(-8));
        if (data.error) lines.push(String(data.error));
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: data.ok ? '숙소 발행 완료' : '숙소 발행 실패',
                meta: 'JP Campus',
                lines: lines.length ? lines : [data.ok ? '완료' : '실패'],
                state: data.ok ? 'success' : 'failed',
                error: data.ok ? null : (data.error || data.stderr || 'failed'),
            });
        }
        showToast(data.ok ? `숙소 ${ids.length}건 발행` : '발행 실패');
        if (data.ok) await refreshBacklog('jpcampus', { silent: true });
    } catch (_) {
        showToast('숙소 발행 요청 실패');
    }
}

async function publishStaySample() {
    if (!confirm('미발행 숙소를 지역별 최대 8건씩 샘플 발행할까요?')) return;
    if (typeof hubOpenProgress === 'function') {
        hubOpenProgress('숙소 샘플 발행 중…', '지역별 8건');
    }
    try {
        const res = await fetch('/api/content/stays/publish', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sample: true, per_region: 8, build: true }),
        });
        const data = await res.json();
        const lines = [];
        if (data.summary) lines.push(`발행 ${data.summary.published} / 전체 ${data.summary.total}`);
        if (data.stdout) lines.push(...String(data.stdout).trim().split('\n').slice(-10));
        if (typeof hubOpenResult === 'function') {
            hubOpenResult({
                title: data.ok ? '샘플 발행 완료' : '샘플 발행 실패',
                meta: 'JP Campus',
                lines: lines.length ? lines : [data.ok ? '완료' : '실패'],
                state: data.ok ? 'success' : 'failed',
                error: data.ok ? null : (data.error || data.stderr || 'failed'),
            });
        }
        showToast(data.ok ? '샘플 발행 완료' : '샘플 발행 실패');
        if (data.ok) await refreshBacklog('jpcampus', { silent: true });
    } catch (_) {
        showToast('샘플 발행 요청 실패');
    }
}
