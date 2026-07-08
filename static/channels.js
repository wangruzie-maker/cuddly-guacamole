/**
 * 微信视频号板块 — 与小红书脚本隔离，通过 /api/channels/* 通信
 */
window.ChannelsApp = (() => {
  let root = null;
  let results = [];
  let taskId = null;
  let pollTimer = null;
  let inited = false;
  let discoverSources = [];
  let cardMode = true;

  function showToast(message) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2600);
  }

  function setView(mode) {
    cardMode = mode === 'card';
    const cards = document.getElementById('chCards');
    const table = document.getElementById('chTable');
    const cardBtn = document.getElementById('chCardViewBtn');
    const tableBtn = document.getElementById('chTableViewBtn');
    if (cards) cards.style.display = cardMode ? 'grid' : 'none';
    if (table) table.classList.toggle('show', !cardMode);
    if (cardBtn) cardBtn.classList.toggle('active', cardMode);
    if (tableBtn) tableBtn.classList.toggle('active', !cardMode);
  }

  function el(html) {
    const t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }

  const SCRIPT_SOURCE_LABEL = { asr: '语音识别', desc: '文案', subtitle: '字幕', chapters: '章节' };

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
  }

  function renderShell() {
    if (!root) return;
    root.innerHTML = `
      <div class="grid">
        <section class="panel">
          <div class="panel-head">视频号 · 输入 / 发现</div>
          <div class="panel-body">
            <textarea id="chInput" rows="6" placeholder="粘贴微信视频号分享链接，支持多行&#10;&#10;来自微信「复制链接」的 channels.weixin.qq.com / weixin.qq.com 链接"></textarea>
            <p class="hint">默认通过 SPH API 解析链接（无需登录）。API 不可用时自动回退 Playwright。</p>
            <label class="checkbox-row"><input type="checkbox" id="chBrowser" /> 浏览器模式（仅备用，无 video_url 时无法口播转写）</label>
            <label class="checkbox-row"><input type="checkbox" id="chTranscribe" checked /> 口播转写（Whisper 语音识别）</label>
            <label class="checkbox-row"><input type="checkbox" id="chLongVideo" checked /> 完整转录长视频</label>
            <label class="checkbox-row" style="align-items:center;gap:8px">
              <span style="min-width:88px">识别模型</span>
              <select id="chWhisperModel" style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--panel-2);color:var(--text)">
                <option value="tiny">tiny · 最快</option>
                <option value="base">base</option>
                <option value="small" selected>small · 推荐</option>
                <option value="medium">medium · 更准</option>
                <option value="large-v3">large-v3 · 最准</option>
              </select>
            </label>
            <div class="actions">
              <button class="btn-primary" id="chExtractBtn">提取并累积</button>
              <button class="btn-secondary" id="chTranscribeBtn">补转写已有视频</button>
              <button class="btn-secondary" id="chClearInputBtn">清空输入</button>
            </div>
            <div class="task-panel idle" id="chTaskPanel">
              <div class="task-head"><strong id="chTaskPhase">任务进度</strong><span id="chTaskCounts">待命</span></div>
              <div class="task-bar"><div class="task-bar-fill" id="chTaskBarFill" style="background:linear-gradient(90deg,#07c160,#10d070)"></div></div>
              <div class="task-label" id="chTaskLabel">提取任务支持进度显示、暂停与取消</div>
              <div class="task-actions">
                <button class="btn-secondary btn-small" id="chPauseBtn" style="display:none">暂停</button>
                <button class="btn-secondary btn-small" id="chResumeBtn" style="display:none">继续</button>
                <button class="btn-danger btn-secondary btn-small" id="chCancelBtn" style="display:none">取消任务</button>
              </div>
            </div>
            <div class="discover-box">
              <h4>关键词 / 账号发现</h4>
              <p class="hint" style="margin-top:0">搜索关键词或指定账号/竞品 → 获取视频号链接 → 一键提取（无需登录）</p>
              <select id="chDiscoverSource" style="width:100%;margin:8px 0;padding:10px;border-radius:10px;border:1px solid var(--border);background:var(--panel-2);color:var(--text)"></select>
              <input type="text" id="chTopic" placeholder="关键词 / 账号名 / 竞品名" style="width:100%;margin:8px 0;padding:10px;border-radius:10px;border:1px solid var(--border);background:var(--panel-2);color:var(--text)" />
              <div class="actions">
                <button class="btn-secondary btn-small" id="chDiscoverBtn">发现链接</button>
                <button class="btn-secondary btn-small" id="chDiscoverExtractBtn">发现并提取</button>
              </div>
              <div id="chDiscoverMsg" class="hint" style="margin-top:8px"></div>
              <ul id="chDiscoverList" class="history-list" style="margin-top:8px"></ul>
            </div>
            <p class="hint" id="chBrowserStatus" style="margin-top:12px"></p>
          </div>
        </section>
        <section class="panel">
          <div class="result-toolbar">
            <div class="stats" id="chStats"></div>
            <div class="view-toggle">
              <button class="btn-secondary active" id="chCardViewBtn">卡片</button>
              <button class="btn-secondary" id="chTableViewBtn">表格</button>
            </div>
            <button class="btn-secondary" id="chExportCsvBtn" disabled>导出 CSV</button>
            <button class="btn-secondary" id="chExportExcelBtn" disabled>导出 Excel（含封面）</button>
            <button class="btn-danger" id="chClearAllBtn" disabled>清空列表</button>
          </div>
          <div class="panel-body">
            <div id="chCards" class="cards"><div class="empty">视频号提取结果会显示在这里</div></div>
            <table id="chTable">
              <thead>
                <tr>
                  <th>状态</th>
                  <th>标题</th>
                  <th>作者</th>
                  <th>文案摘要</th>
                  <th>视频脚本</th>
                  <th>赞</th>
                  <th>评论</th>
                  <th>分享</th>
                  <th>收藏</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody id="chTableBody"></tbody>
            </table>
          </div>
        </section>
      </div>
    `;

    document.getElementById('chExtractBtn').addEventListener('click', () => extract().catch((e) => alert(e.message)));
    document.getElementById('chTranscribeBtn').addEventListener('click', () => transcribeAll().catch((e) => alert(e.message)));
    document.getElementById('chClearInputBtn').addEventListener('click', () => { document.getElementById('chInput').value = ''; });
    document.getElementById('chClearAllBtn').addEventListener('click', clearAll);
    document.getElementById('chCardViewBtn').addEventListener('click', () => setView('card'));
    document.getElementById('chTableViewBtn').addEventListener('click', () => setView('table'));
    document.getElementById('chExportCsvBtn').addEventListener('click', () => exportCsv().catch((e) => alert(e.message)));
    document.getElementById('chExportExcelBtn').addEventListener('click', () => exportExcel().catch((e) => alert(e.message)));
    document.getElementById('chPauseBtn').addEventListener('click', () => taskAction('pause'));
    document.getElementById('chResumeBtn').addEventListener('click', () => taskAction('resume'));
    document.getElementById('chCancelBtn').addEventListener('click', () => taskAction('cancel'));
    document.getElementById('chDiscoverBtn').addEventListener('click', () => discover(false));
    document.getElementById('chDiscoverExtractBtn').addEventListener('click', () => discover(true));
  }

  function renderTask(task) {
    const panel = document.getElementById('chTaskPanel');
    if (!task) {
      panel.classList.add('idle');
      panel.classList.remove('active', 'done');
      document.getElementById('chTaskPhase').textContent = '任务进度';
      document.getElementById('chTaskCounts').textContent = '待命';
      document.getElementById('chTaskBarFill').style.width = '0%';
      document.getElementById('chTaskLabel').textContent = '提取任务支持进度显示、暂停与取消';
      document.getElementById('chPauseBtn').style.display = 'none';
      document.getElementById('chResumeBtn').style.display = 'none';
      document.getElementById('chCancelBtn').style.display = 'none';
      document.getElementById('chExtractBtn').disabled = false;
      taskId = null;
      return;
    }

    taskId = task.id;
    const running = task.status === 'running' || task.status === 'paused';
    document.getElementById('chExtractBtn').disabled = running;
    panel.classList.toggle('idle', !running && task.status !== 'completed');
    panel.classList.toggle('active', running);
    panel.classList.toggle('done', task.status === 'completed');

    document.getElementById('chTaskPhase').textContent =
      task.status === 'paused' ? '已暂停' : task.phase === 'media' ? '后台处理' : '提取视频号';
    document.getElementById('chTaskCounts').textContent =
      `${task.overall_done || 0} / ${task.overall_total || task.extract_total || 0}`;
    document.getElementById('chTaskBarFill').style.width = `${Math.min(100, task.progress_pct || 0)}%`;
    document.getElementById('chTaskLabel').textContent = task.message + (task.current_label ? ` · ${task.current_label}` : '');

    document.getElementById('chPauseBtn').style.display = task.status === 'running' ? '' : 'none';
    document.getElementById('chResumeBtn').style.display = task.status === 'paused' ? '' : 'none';
    document.getElementById('chCancelBtn').style.display = running ? '' : 'none';
  }

  let resumePendingOnce = false;
  let whisperStatus = { model: 'small', ready: false, loaded: false };

  async function refreshWhisperStatus(model) {
    try {
      const q = model ? `?model=${encodeURIComponent(model)}` : '';
      const resp = await fetch(`/api/whisper/status${q}`);
      if (resp.ok) whisperStatus = await resp.json();
    } catch (_) {}
    return whisperStatus;
  }

  function transcribePendingHint(r) {
    const model = r.whisper_model || whisperModelValue() || whisperStatus.model || 'small';
    if (whisperStatus.loaded && whisperStatus.model === model) {
      return `Whisper ${model} 已成功调用，正在转写口播…`;
    }
    if (whisperStatus.ready) {
      return `Whisper ${model} 本地模型已就绪，正在调用识别…`;
    }
    return `Whisper ${model} 未检测到本地模型，请先运行 ./setup_whisper.sh`;
  }

  function scriptBlock(r) {
    if (r.video_script_status === 'pending') {
      return `
        <div class="script-box">
          <div class="script-label">视频脚本 · 转写中…</div>
          <p class="script-text" style="color:#4a6288">${escapeHtml(transcribePendingHint(r))}</p>
        </div>
      `;
    }
    if (!r.video_script) {
      if (r.video_script_status === 'failed') {
        return `
          <div class="script-box">
            <div class="script-label">视频脚本 · 转写失败</div>
            <p class="script-text" style="color:var(--muted)">${escapeHtml(r.video_script_error || '请重新提取链接后再点「补转写」')}</p>
          </div>
        `;
      }
      if (r.status === '成功' && !r.video_url && r.video_script_status === 'none') {
        return `
          <div class="script-box">
            <div class="script-label">视频脚本 · 未生成</div>
            <p class="script-text" style="color:var(--muted)">未获取到 video_url，请取消「浏览器模式」重新提取，或点「补转写已有视频」</p>
          </div>
        `;
      }
      return '';
    }
    const label = SCRIPT_SOURCE_LABEL[r.video_script_source] || r.video_script_source || '脚本';
    return `
      <div class="script-box">
        <div class="script-label">视频脚本 · ${escapeHtml(label)}</div>
        <p class="script-text">${escapeHtml(r.video_script)}</p>
      </div>
    `;
  }

  function renderCardsList() {
    const cards = document.getElementById('chCards');
    if (!cards) return;
    if (!results.length) {
      cards.innerHTML = '<div class="empty">视频号提取结果会显示在这里</div>';
      return;
    }
    cards.innerHTML = results.map((r) => `
      <article class="card">
        <div class="card-head">
          <h3 class="card-title">${escapeHtml(r.title || r.url || '（无标题）')}</h3>
          <span class="tag ${r.status === '成功' ? 'ok' : 'err'}">${escapeHtml(r.status)}</span>
        </div>
        <div class="card-body">
          <div class="meta">
            <span>作者：${escapeHtml(r.author || '-')}</span>
            <span>赞 ${escapeHtml(r.liked_count || '-')}</span>
            <span>${escapeHtml(r.extract_mode || '')}</span>
          </div>
          <p class="desc" style="color:var(--text)">${escapeHtml((r.desc || r.error || '').slice(0, 200))}</p>
          ${scriptBlock(r)}
          ${r.video_url ? `<div class="link-row">视频：${escapeHtml(r.video_url.slice(0, 80))}…</div>` : ''}
          ${r.feed_id && r.status === '成功' ? `
            <div class="card-actions">
              ${!r.video_script && r.video_script_status !== 'pending' ? `
                <button class="btn-secondary btn-small" data-transcribe="${escapeHtml(r.feed_id)}">提取口播脚本</button>
              ` : r.video_script ? `
                <button class="btn-secondary btn-small" data-transcribe="${escapeHtml(r.feed_id)}" data-force="1">重新转写</button>
              ` : ''}
            </div>
          ` : ''}
        </div>
      </article>
    `).join('');

    cards.querySelectorAll('[data-transcribe]').forEach((btn) => {
      btn.addEventListener('click', () => transcribeOne(
        btn.getAttribute('data-transcribe'),
        btn.getAttribute('data-force') === '1'
      ));
    });
  }

  function renderTableList() {
    const tbody = document.getElementById('chTableBody');
    if (!tbody) return;
    if (!results.length) {
      tbody.innerHTML = '';
      return;
    }
    tbody.innerHTML = results.map((r) => {
      const scriptPreview = r.video_script
        ? r.video_script.slice(0, 60)
        : r.video_script_status === 'pending'
          ? '转写中…'
          : r.video_script_status === 'failed'
            ? (r.video_script_error || '转写失败').slice(0, 40)
            : '-';
      return `
        <tr>
          <td>${escapeHtml(r.status || '-')}</td>
          <td>${escapeHtml((r.title || '-').slice(0, 60))}</td>
          <td>${escapeHtml(r.author || '-')}</td>
          <td>${escapeHtml((r.desc || r.error || '-').slice(0, 80))}</td>
          <td>${escapeHtml(scriptPreview)}</td>
          <td>${escapeHtml(r.liked_count || '-')}</td>
          <td>${escapeHtml(r.comment_count || '-')}</td>
          <td>${escapeHtml(r.share_count || '-')}</td>
          <td>${escapeHtml(r.collect_count || '-')}</td>
          <td>${r.feed_id && r.status === '成功' ? `
            ${!r.video_script && r.video_script_status !== 'pending' ? `
              <button class="btn-secondary btn-small" data-transcribe="${escapeHtml(r.feed_id)}">转写</button>
            ` : r.video_script ? `
              <button class="btn-secondary btn-small" data-transcribe="${escapeHtml(r.feed_id)}" data-force="1">重转写</button>
            ` : ''}
          ` : '-'}</td>
        </tr>
      `;
    }).join('');

    tbody.querySelectorAll('[data-transcribe]').forEach((btn) => {
      btn.addEventListener('click', () => transcribeOne(
        btn.getAttribute('data-transcribe'),
        btn.getAttribute('data-force') === '1'
      ));
    });
  }

  function renderResults(data) {
    results = data.results || [];
    const ok = data.success || 0;
    const pending = data.pending_transcriptions ?? results.filter((r) => r.video_script_status === 'pending').length;
    if (window.updateReturnPanelData) {
      window.updateReturnPanelData('channels', { count: data.count || 0, success: ok, pending_transcriptions: pending });
    }
    document.getElementById('chStats').innerHTML = `
      <div class="stat">共 <strong>${data.count || 0}</strong> 条</div>
      <div class="stat">成功 <strong>${ok}</strong></div>
      <div class="stat stat-pending">转写中 <strong>${pending}</strong></div>
    `;
    document.getElementById('chClearAllBtn').disabled = !results.length;
    document.getElementById('chExportCsvBtn').disabled = !results.length;
    document.getElementById('chExportExcelBtn').disabled = !results.length;
    document.getElementById('chTranscribeBtn').disabled = !results.some(
      (r) => r.status === '成功' && (r.video_url || r.url) && r.video_script_status !== 'pending' && !r.video_script
    );

    renderCardsList();
    renderTableList();

    if (pending && !pollTimer) startPoll();
    if (pending) {
      const pendingModel = results.find((r) => r.video_script_status === 'pending')?.whisper_model;
      refreshWhisperStatus(pendingModel).then(() => {
        renderCardsList();
        renderTableList();
      });
    }
  }

  async function ensureServerOnline() {
    try {
      const resp = await fetch('/api/channels/health', { cache: 'no-store' });
      return resp.ok;
    } catch (_) {
      return false;
    }
  }

  function triggerDownload(url) {
    const frame = document.createElement('iframe');
    frame.style.display = 'none';
    frame.src = url;
    document.body.appendChild(frame);
    setTimeout(() => frame.remove(), 120000);
  }

  async function exportCsv() {
    if (!results.length) {
      alert('没有可导出的数据');
      return;
    }
    if (!(await ensureServerOnline())) {
      alert('服务未连接，请先运行 ./open_app.sh 启动服务');
      return;
    }
    showToast(`正在生成 CSV（${results.length} 条）…`);
    triggerDownload(`/api/channels/download/csv?t=${Date.now()}`);
    setTimeout(() => showToast(`CSV 下载已开始（${results.length} 条）`), 800);
  }

  async function exportExcel() {
    if (!results.length) {
      alert('没有可导出的数据');
      return;
    }
    if (!(await ensureServerOnline())) {
      alert('服务未连接，请先运行 ./open_app.sh 启动服务');
      return;
    }
    const btn = document.getElementById('chExportExcelBtn');
    btn.disabled = true;
    btn.textContent = '生成 Excel 中…';
    showToast(`正在生成 Excel（含封面，约需 10–30 秒）…`);
    try {
      triggerDownload(`/api/channels/download/excel?t=${Date.now()}`);
      setTimeout(() => showToast('Excel 下载已开始'), 1500);
    } finally {
      setTimeout(() => {
        btn.disabled = results.length === 0;
        btn.textContent = '导出 Excel（含封面）';
      }, 3000);
    }
  }

  async function loadAccumulated() {
    const resp = await fetch('/api/channels/accumulated');
    const data = await resp.json();
    renderResults(data);
  }

  async function loadBrowserStatus() {
    try {
      const resp = await fetch('/api/channels/browser/status');
      const data = await resp.json();
      document.getElementById('chBrowserStatus').textContent = data.message || '';
    } catch (_) {}
  }

  async function loadTask() {
    const resp = await fetch('/api/channels/tasks/current');
    const data = await resp.json();
    if (data.accumulated) renderResults(data.accumulated);
    renderTask(data.task);
    if (data.task && (data.task.status === 'running' || data.task.status === 'paused')) {
      startPoll();
    }
  }

  async function maybeResumePendingTranscriptions(pending) {
    if (resumePendingOnce || !pending || pending <= 0) return;
    resumePendingOnce = true;
    try {
      const resp = await fetch('/api/channels/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          long_video: document.getElementById('chLongVideo').checked,
          whisper_model: whisperModelValue(),
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.accumulated) renderResults(data.accumulated);
        renderTask(data.task);
      }
    } catch (_) {
      resumePendingOnce = false;
    }
  }

  function startPoll() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      try {
        const resp = await fetch('/api/channels/tasks/current');
        const data = await resp.json();
        if (data.accumulated) renderResults(data.accumulated);
        renderTask(data.task);
        const pending = data.accumulated?.pending_transcriptions ?? 0;
        if (pending) {
          refreshWhisperStatus(whisperModelValue());
        }
        const running = data.task && (data.task.status === 'running' || data.task.status === 'paused');
        if (pending > 0 && !running) {
          await maybeResumePendingTranscriptions(pending);
        }
        if (data.task && ['completed', 'cancelled', 'failed'].includes(data.task.status) && pending <= 0) {
          clearInterval(pollTimer);
          pollTimer = null;
          setTimeout(() => renderTask(null), 4000);
        } else if (!running && pending <= 0) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
      } catch (_) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }, 1500);
  }

  function whisperModelValue() {
    const el = document.getElementById('chWhisperModel');
    return el ? el.value : 'small';
  }

  async function transcribeOne(feedId, force = false) {
    const resp = await fetch('/api/channels/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feed_ids: [feedId],
        force,
        long_video: document.getElementById('chLongVideo').checked,
        whisper_model: whisperModelValue(),
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '转写失败');
    if (data.accumulated) renderResults(data.accumulated);
    renderTask(data.task);
    startPoll();
  }

  async function transcribeAll() {
    const resp = await fetch('/api/channels/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        long_video: document.getElementById('chLongVideo').checked,
        whisper_model: whisperModelValue(),
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '转写失败');
    if (data.accumulated) renderResults(data.accumulated);
    renderTask(data.task);
    startPoll();
  }

  async function extract() {
    const text = document.getElementById('chInput').value.trim();
    if (!text) {
      alert('请先粘贴视频号链接');
      return;
    }
    const resp = await fetch('/api/channels/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        use_browser: document.getElementById('chBrowser').checked,
        transcribe_video: document.getElementById('chTranscribe').checked,
        long_video: document.getElementById('chLongVideo').checked,
        whisper_model: whisperModelValue(),
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '提取失败');
    document.getElementById('chInput').value = '';
    if (data.accumulated) renderResults(data.accumulated);
    renderTask(data.task);
    startPoll();
  }

  async function taskAction(action) {
    if (!taskId) return;
    const resp = await fetch(`/api/channels/tasks/${encodeURIComponent(taskId)}/${action}`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) alert(data.detail || '操作失败');
    else renderTask(data.task);
  }

  async function loadDiscoverSources() {
    try {
      const resp = await fetch('/api/channels/discover/sources');
      const data = await resp.json();
      discoverSources = data.sources || [];
      const sel = document.getElementById('chDiscoverSource');
      if (!sel) return;
      sel.innerHTML = discoverSources.map((s) =>
        `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`
      ).join('');
    } catch (_) {}
  }

  async function discover(thenExtract) {
    const keyword = document.getElementById('chTopic').value.trim();
    const sourceId = document.getElementById('chDiscoverSource')?.value || 'channels_search_keyword';
    if (!keyword) {
      alert('请填写关键词或账号名');
      return;
    }
    const endpoint = thenExtract ? '/api/channels/discover/extract' : '/api/channels/discover/run';
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_id: sourceId,
        keyword,
        limit: 20,
        use_browser: document.getElementById('chBrowser').checked,
        transcribe_video: document.getElementById('chTranscribe').checked,
        long_video: document.getElementById('chLongVideo').checked,
        whisper_model: whisperModelValue(),
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      alert(data.detail || '发现失败');
      return;
    }
    document.getElementById('chDiscoverMsg').textContent = data.message || '';
    const items = data.items || [];
    const list = document.getElementById('chDiscoverList');
    if (!items.length) {
      list.innerHTML = '<li class="history-meta">暂无链接</li>';
    } else {
      list.innerHTML = items.map((i) => `
        <li class="history-item">
          <div class="history-name">${escapeHtml(i.title || i.url)}</div>
          <div class="history-meta">${escapeHtml(i.score || '')} ${escapeHtml(i.url)}</div>
        </li>
      `).join('');
    }
    if (data.extract) {
      renderTask(data.extract);
      startPoll();
    }
  }

  async function clearAll() {
    if (!results.length) return;
    if (!confirm(`确定清空 ${results.length} 条视频号记录？`)) return;
    await fetch('/api/channels/accumulated', { method: 'DELETE' });
    results = [];
    renderResults({ count: 0, success: 0, results: [] });
  }

  function init() {
    root = document.getElementById('channelsApp');
    if (!root) return;
    // 热更新后旧 DOM 可能缺少导出按钮，检测到则重建界面
    if (!inited || !document.getElementById('chExportCsvBtn')) {
      renderShell();
      inited = true;
    }
    loadAccumulated().catch(() => {});
    loadDiscoverSources().catch(() => {});
    loadBrowserStatus().catch(() => {});
    loadTask().catch(() => {});
  }

  return { init };
})();
