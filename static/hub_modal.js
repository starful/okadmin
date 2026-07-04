/** Shared progress / result modal (site hub, dashboard pipeline). */
let hubModalBusy = false;

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
    };
}

function hubPhaseHtml(phase, running) {
    if (!running) return '';
    const gen = phase === 'deploy' ? 'done' : 'active';
    const dep = phase === 'deploy' ? 'active' : '';
    return `<div class="hub-modal-phases">
        <span class="hub-phase ${gen}">① 생성·빌드</span>
        <span class="hub-phase-arrow">→</span>
        <span class="hub-phase ${dep || 'idle'}">② 배포</span>
    </div>`;
}

function hubLinesHtml(lines, highlightFirst) {
    const items = Array.isArray(lines) ? lines : [];
    if (!items.length) return '<p class="mono" style="color:#666;margin:0">결과 없음</p>';
    let html = '<ul class="hub-modal-lines">';
    items.forEach((line, i) => {
        const cls = highlightFirst && i === 0 && line.startsWith('+ 추가') ? ' class="created-highlight"' : '';
        html += `<li${cls}>${hubEsc(line)}</li>`;
    });
    html += '</ul>';
    return html;
}

function hubLogHtml(full, running, phase) {
    const f = (full || '').trim();
    if (!f) return '';
    const label = running && phase === 'deploy' ? '상세 로그 (deploy + pipeline)' : '상세 로그';
    return `<p class="hub-modal-log-label">${hubEsc(label)}</p>`
        + `<pre class="hub-modal-log">${hubEsc(f)}</pre>`;
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

function hubOpenProgress(title, detail) {
    const { overlay, modal, title: titleEl, meta, body } = hubModalEls();
    if (!overlay || !body) return;
    hubModalBusy = true;
    if (titleEl) titleEl.textContent = title || '진행 중…';
    if (meta) meta.textContent = detail || '';
    body.innerHTML = '<p class="mono hub-progress-pulse">● 진행 중…</p>'
        + (detail ? `<p class="mono" style="color:#aaa;margin:8px 0 0;font-size:11px">${hubEsc(detail)}</p>` : '');
    modal?.classList.add('progress');
    overlay.classList.add('open');
}

function hubUpdateProgress(view) {
    const { title: titleEl, meta, body } = hubModalEls();
    if (!body || !hubModalBusy) return;
    if (view.title && titleEl) titleEl.textContent = view.title;
    if (view.meta !== undefined && meta) meta.textContent = view.meta;
    body.innerHTML = hubProgressBody(view);
}

function hubFinishProgress() {
    hubModalBusy = false;
    hubModalEls().modal?.classList.remove('progress');
}

function hubCloseModal() {
    if (hubModalBusy) return;
    hubModalEls().overlay?.classList.remove('open');
}

function hubOpenResult(view) {
    hubFinishProgress();
    const { overlay, title: titleEl, meta, body } = hubModalEls();
    if (!overlay || !body) return;
    if (titleEl) titleEl.textContent = view.title || '작업 결과';
    if (meta) meta.textContent = view.meta || '';
    let html = '';
    if (view.error) {
        html += `<p class="mono" style="color:#f88;margin:0 0 8px">${hubEsc(view.error)}</p>`;
    }
    html += hubPhaseHtml(view.phase, false);
    html += hubLinesHtml(view.lines, true);
    html += hubLogHtml(view.logFull, false, view.phase);
    body.innerHTML = html;
    overlay.classList.add('open');
    hubModalEls().close?.focus();
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

    const fullText = (opts.deploy_log_tail && running && phase === 'deploy')
        ? opts.deploy_log_tail + '\n\n--- pipeline ---\n\n' + (logTail || '')
        : (logTail || '');

    let modalTitle = title;
    if (running && phase === 'deploy') modalTitle = '② 배포 중';
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
    };
}

function initHubModal() {
    hubModalEls().close?.addEventListener('click', hubCloseModal);
    document.getElementById('hub-results-overlay')?.addEventListener('click', e => {
        if (e.target?.id === 'hub-results-overlay' && !hubModalBusy) hubCloseModal();
    });
    document.addEventListener('keydown', e => {
        if (e.key !== 'Escape' || hubModalBusy) return;
        const overlay = document.getElementById('hub-results-overlay');
        if (overlay?.classList.contains('open')) hubCloseModal();
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHubModal);
} else {
    initHubModal();
}
