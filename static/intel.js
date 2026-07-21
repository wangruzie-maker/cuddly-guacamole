/* 内容情报 — 轻量能力工作台：获取依据 / 选题分析 / 语料资产 */
(function () {
  const API = '/api/intel';
  const PAGE_SIZE = 10;
  const XHS_LOGIN_OK_KEY = 'intel_xhs_login_ok';
  const XHS_LOGIN_AT_KEY = 'intel_xhs_login_at';
  let inited = false;
  let topics = [];
  const topicPages = {};
  const topicItemFilters = {};
  const selectedRadarItems = new Map();
  const transcriptionByUrl = new Map();
  const topicTranscriptionStatus = new Map();
  const topicRunResults = new Map();
  let corpusBatch = 0;
  let creativeBrief = '';
  let latestSuggestedTopics = [];
  const topicCopyStates = new Map();
  let currentIntelTab = 'topics';
  let assetsQuery = '';
  let assetsOffset = 0;
  let selectedAssetId = null;
  let assetsGroupBy = 'topic_date';
  let assetsTopicFilter = '';
  let assetsTopicNames = null;
  let assetsShowAdd = false;
  let selectedAssetIds = new Set();
  let latestAssetItems = [];
  let trackedOverviewChart = null;
  let trackedDetailChart = null;
  let selectedTrackedId = null;
  let latestTrackedItems = [];
  let defaultTranscriptionMode = 'full'; // full | simple
  const topicTranscriptionMode = {};
  let transcriptionFloatEl = null;
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'style') node.style.cssText = v;
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null) node.setAttribute(k, v);
    });
    const kids = Array.isArray(children) ? children : (children == null ? [] : [children]);
    kids.forEach((c) => {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
    });
    return node;
  }

  async function api(path, options) {
    const resp = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!resp.ok) {
      let msg = `请求失败 (${resp.status})`;
      try {
        const data = await resp.json();
        msg = data.detail || msg;
      } catch (e) {}
      throw new Error(msg);
    }
    return resp.json();
  }

  function fmtNum(n) {
    n = Number(n) || 0;
    if (n >= 10000) return (n / 10000).toFixed(1) + '万';
    return String(n);
  }

  function inputStyle(width) {
    return `padding:8px 10px;border-radius:10px;border:1px solid var(--border);background:var(--panel);color:var(--text);${width ? `width:${width};` : 'flex:1 1 200px;'}`;
  }

  function compactInputStyle(width) {
    return `padding:5px 8px;border-radius:8px;border:1px solid var(--border);background:var(--panel);color:var(--text);font-size:13px;width:${width || '100%'};box-sizing:border-box;`;
  }

  /** Reliable open/close fold (native <details> can get stuck in this UI). */
  function makeFold(title, bodyChildren, opts) {
    const options = opts || {};
    let open = !!options.defaultOpen;
    const body = el('div', {
      style: options.bodyStyle || 'margin-top:6px;',
    }, Array.isArray(bodyChildren) ? bodyChildren : [bodyChildren]);
    body.hidden = !open;
    const toggle = () => {
      open = !open;
      body.hidden = !open;
      head.textContent = `${open ? '▼' : '▶'} ${title}`;
    };
    const head = options.compact
      ? el('button', {
          type: 'button',
          style: 'border:0;background:none;padding:0;margin:0;color:var(--accent);font-size:12px;cursor:pointer;text-align:left;',
          onclick: toggle,
        }, [`${open ? '▼' : '▶'} ${title}`])
      : el('button', {
          type: 'button',
          class: 'btn-secondary btn-small',
          style: 'width:100%;justify-content:flex-start;text-align:left;font-weight:600;',
          onclick: toggle,
        }, [`${open ? '▼' : '▶'} ${title}`]);
    return el('div', { style: options.wrapStyle || 'margin-bottom:8px;' }, [head, body]);
  }

  function cleanCorpusPreview(text) {
    let t = String(text || '');
    t = t.replace(/#[^\s#\[\]]*\[话题\]#?/g, ' ');
    t = t.replace(/#[\w\u4e00-\u9fff]+/g, ' ');
    t = t.replace(/\[[^\]]{0,12}话题[^\]]*\]/g, ' ');
    t = t.replace(/\s+/g, ' ').trim();
    return t.slice(0, 120);
  }

  function isRunMessageWarning(msg) {
    if (!msg) return false;
    return /错误|失败|未登录|login|error/i.test(msg);
  }

  function postMetrics(post) {
    const m = post.metrics || {};
    return {
      liked: m.liked_count ?? post.latest_liked ?? 0,
      collected: m.collected_count ?? post.latest_collected ?? 0,
      comment: m.comment_count ?? post.latest_comment ?? 0,
      share: m.share_count ?? post.latest_share ?? 0,
    };
  }

  function renderMetrics(item) {
    const parts = [
      `转 ${fmtNum(item.share_count)}`,
      `赞 ${fmtNum(item.liked_count)}`,
      `评 ${fmtNum(item.comment_count)}`,
      `播 ${fmtNum(item.view_count)}`,
      `搜 ${item.keyword || '-'}`,
      `藏 ${fmtNum(item.collected_count)}`,
    ];
    return el('span', { class: 'intel-metrics', style: 'font-size:12px;color:var(--muted);white-space:nowrap;' }, [parts.join(' · ')]);
  }

  function ensureChartJs() {
    if (window.Chart) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('Chart.js 加载失败（需联网）'));
      document.head.appendChild(s);
    });
  }

  function proxiedImageUrl(url) {
    if (!url) return '';
    if (url.startsWith('/api/media/')) return url;
    return /^https?:\/\//i.test(url) ? `/api/image-proxy?url=${encodeURIComponent(url)}` : url;
  }

  function extractedCoverUrl(result) {
    const localPath = (result?.local_image_paths || [])[0] || '';
    if (localPath) {
      const parts = localPath.split('/').filter(Boolean);
      if (parts.length >= 2) {
        return `/api/media/${encodeURIComponent(parts[parts.length - 2])}/${encodeURIComponent(parts[parts.length - 1])}`;
      }
    }
    return proxiedImageUrl((result?.image_urls || [])[0] || '');
  }

  function transcriptionKindLabel(item, transcription) {
    const noteType = item.content_type || item.note_type || '';
    if (noteType === '视频') return '脚本';
    if (noteType === '图文') return 'OCR';
    return transcription?.kind || '正文';
  }

  function transcriptionStatusLabel(item, transcription, result) {
    const meta = transcription || item.transcription || {};
    if (meta.label) return meta.label;
    const progress = meta.progress;
    if (progress?.label) return progress.label;
    const noteType = item.content_type || item.note_type || '';
    const scriptStatus = result?.video_script_status;
    const ocrStatus = result?.image_ocr_status;
    const scriptSource = result?.video_script_source || meta.script_source || '';
    const hasRealScript = !!(result?.video_script && !['desc', 'desc_fallback'].includes(scriptSource));
    const hasOcr = !!(result?.image_ocr_text || meta.has_ocr);
    if (scriptStatus === 'pending' || (noteType === '视频' && scriptStatus === 'pending')) {
      return '视频脚本转写中…';
    }
    if (ocrStatus === 'pending' || (noteType === '图文' && ocrStatus === 'pending')) {
      return '图片 OCR 中…';
    }
    if (scriptStatus === 'failed' || scriptSource === 'desc' || scriptSource === 'desc_fallback') {
      if (result?.desc || meta.has_desc_only) return '仅正文（脚本未拿到）';
      return '脚本转写失败';
    }
    if (ocrStatus === 'failed') {
      if (result?.desc || meta.has_desc_only) return '仅正文（OCR 失败）';
      return 'OCR 失败';
    }
    if (meta.status === 'completed') {
      if (meta.label) return meta.label;
      if (result?.extract_mode === 'simple' || meta.extract_mode === 'simple') return '已完成（简单）';
      if (noteType === '视频' && hasRealScript) return hasOcr ? '已完成（脚本+OCR）' : '已完成（脚本）';
      if (noteType === '图文' && hasOcr) return '已完成（OCR）';
      return '已完成';
    }
    if (meta.status === 'partial' || meta.has_desc_only) return '仅正文';
    if (meta.status === 'failed') return '转录失败';
    if (meta.status === 'running') return '转录中…';
    return '未转录';
  }

  function transcriptionProgressPercent(item, transcription, result) {
    const label = transcriptionStatusLabel(item, transcription, result);
    if (/已完成/.test(label)) return 100;
    if (/仅正文/.test(label)) return 70;
    if (/失败/.test(label)) return 100;
    if (/转写中|OCR 中|转录中/.test(label)) return 55;
    if (transcription?.status === 'running') return 35;
    if (/未转录|待/.test(label)) return 0;
    return null;
  }

  function setTopicTranscriptionStatus(topicId, message, tone = 'muted') {
    topicTranscriptionStatus.set(topicId, { message, tone });
    const status = document.getElementById(`intelTranscriptionStatus-${topicId}`);
    if (status) {
      status.textContent = message;
      status.style.color = tone === 'ok' ? 'var(--ok)' : (tone === 'error' ? 'var(--err)' : 'var(--muted)');
    }
  }

  function findExtractedResult(item, results) {
    return (results || []).find((result) => {
      if (result.url && result.url === item.url) return true;
      return item.feed_id && result.feed_id && String(item.feed_id) === String(result.feed_id);
    });
  }

  function showTranscriptionFloat(item, transcription, result) {
    if (transcriptionFloatEl) transcriptionFloatEl.remove();
    const text = result?.video_script || result?.image_ocr_text || result?.desc
      || item.transcription?.text || transcription?.result?.video_script
      || transcription?.result?.image_ocr_text || transcription?.text || '';
    const kind = transcriptionKindLabel(item, item.transcription || transcription);
    const title = item.title || item.url || '转录内容';
    const len = text.length;
    const width = len > 1200 ? 'min(520px, 42vw)' : (len > 400 ? 'min(420px, 38vw)' : 'min(340px, 34vw)');
    const maxHeight = len > 800 ? '72vh' : (len > 300 ? '56vh' : '42vh');
    transcriptionFloatEl = el('div', {
      style: 'position:fixed;top:72px;right:18px;bottom:18px;width:' + width + ';max-height:calc(100vh - 90px);z-index:10050;display:flex;flex-direction:column;border:1px solid var(--border);border-radius:14px;background:var(--panel);box-shadow:0 18px 48px rgba(0,0,0,.22);',
    }, [
      el('div', {
        style: 'display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:12px 14px;border-bottom:1px solid var(--border);',
      }, [
        el('div', { style: 'flex:1;min-width:0;' }, [
          el('div', { style: 'font-size:14px;font-weight:700;line-height:1.35;' }, [title]),
          el('div', { class: 'hint', style: 'font-size:11.5px;margin-top:4px;' }, [
            `${kind} · ${transcriptionStatusLabel(item, transcription, result)}`,
          ]),
        ]),
        el('button', {
          class: 'btn-secondary btn-small',
          type: 'button',
          onclick: () => {
            if (transcriptionFloatEl) {
              transcriptionFloatEl.remove();
              transcriptionFloatEl = null;
            }
          },
        }, ['关闭']),
      ]),
      el('div', {
        style: `flex:1;overflow:auto;padding:12px 14px;font-size:12.5px;line-height:1.65;white-space:pre-wrap;max-height:${maxHeight};`,
      }, [text || '暂无转录内容，请先启动转录。']),
    ]);
    document.body.appendChild(transcriptionFloatEl);
  }

  function renderManualTranscriptionResults(accumulated, requestedUrls = []) {
    const container = document.getElementById('intelManualResults');
    if (!container) return;
    const requested = new Set(requestedUrls);
    let results = accumulated?.results || [];
    if (requested.size) {
      const matched = results.filter((item) => requested.has(item.url));
      if (matched.length) results = matched;
    }
    container.innerHTML = '';
    results.slice(-10).reverse().forEach((item) => {
      const cover = extractedCoverUrl(item);
      const text = item.video_script || item.image_ocr_text || item.desc || '';
      const card = el('div', {
        style: 'display:grid;grid-template-columns:48px 1fr;gap:9px;padding:8px 0;border-top:1px solid var(--border);',
      }, [
        cover
          ? el('img', { src: cover, alt: '转录内容封面', style: 'width:48px;height:48px;object-fit:cover;border-radius:7px;' })
          : el('div', { style: 'width:48px;height:48px;border-radius:7px;background:var(--panel-2);' }, []),
        el('div', {}, [
          el('div', { style: 'font-size:12.5px;font-weight:600;' }, [item.title || item.url || '转录内容']),
          el('div', { class: 'hint', style: 'font-size:11px;margin-top:2px;' }, [
            `${item.status || '处理中'} · ${item.video_script ? '视频脚本' : (item.image_ocr_text ? '图片 OCR' : '正文')}`,
          ]),
          text
            ? el('button', {
                class: 'btn-secondary btn-small',
                type: 'button',
                style: 'margin-top:4px;font-size:11px;',
                onclick: () => showTranscriptionFloat({ title: item.title, url: item.url, content_type: item.note_type }, null, item),
              }, ['查看转录'])
            : el('span', { class: 'hint', style: 'font-size:11px;' }, ['结果生成中…']),
        ]),
      ]);
      container.appendChild(card);
    });
  }

  async function pollManualTranscription(platform, taskId, requestedUrls) {
    try {
      const endpoint = platform === 'channels'
        ? '/api/channels/tasks/current'
        : `/api/tasks/${encodeURIComponent(taskId)}`;
      if (platform !== 'channels' && !taskId) return;
      const resp = await fetch(endpoint);
      if (!resp.ok) throw new Error(`状态查询失败 (${resp.status})`);
      const data = await resp.json();
      if (data.accumulated) renderManualTranscriptionResults(data.accumulated, requestedUrls);
      const task = data.task || {};
      const pending = Number(data.accumulated?.pending_transcriptions || 0)
        + Number(data.accumulated?.pending_ocr || 0);
      if (!['completed', 'cancelled', 'failed'].includes(task.status) || pending > 0) {
        window.setTimeout(() => pollManualTranscription(platform, taskId, requestedUrls), 1500);
        return;
      }
      const msg = document.getElementById('intelManualExtractMsg');
      if (msg) {
        msg.textContent = task.status === 'failed' ? `转录失败：${task.message || '任务失败'}` : '转录完成，结果已显示在下方。';
        msg.style.color = task.status === 'failed' ? 'var(--err)' : 'var(--ok)';
      }
    } catch (e) {
      const msg = document.getElementById('intelManualExtractMsg');
      if (msg) {
        msg.textContent = e.message;
        msg.style.color = 'var(--err)';
      }
    }
  }

  async function pollInlineTranscription(topicId, taskId, selected) {
    try {
      const data = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`).then(async (resp) => {
        if (!resp.ok) throw new Error(`状态查询失败 (${resp.status})`);
        return resp.json();
      });
      const task = data.task || {};
      const results = data.accumulated?.results || [];
      const pendingOcr = Number(data.accumulated?.pending_ocr || 0);
      const pendingScript = results.filter((r) => r.video_script_status === 'pending').length;
      selected.forEach((item) => {
        const result = findExtractedResult(item, results);
        const noteType = item.content_type || item.note_type || '';
        let status = 'running';
        if (result) {
          const mode = result.extract_mode || transcriptionByUrl.get(item.url)?.extract_mode || '';
          const scriptSource = result.video_script_source || '';
          const hasRealScript = !!(result.video_script && !['desc', 'desc_fallback'].includes(scriptSource));
          const hasOcr = !!result.image_ocr_text;
          const pending = result.video_script_status === 'pending' || result.image_ocr_status === 'pending';
          if (mode === 'simple') {
            status = (result.status === '成功' && (result.desc || result.title)) ? 'completed' : (task.status === 'failed' ? 'failed' : 'running');
          } else if (pending) {
            status = 'running';
          } else if (noteType === '视频' && hasRealScript) {
            status = 'completed';
          } else if (noteType === '图文' && hasOcr) {
            status = 'completed';
          } else if (result.status === '成功' && (result.desc || hasRealScript || hasOcr)) {
            status = (hasRealScript || hasOcr) ? 'completed' : 'partial';
          } else if (task.status === 'failed') {
            status = 'failed';
          }
        } else if (task.status === 'failed') {
          status = 'failed';
        }
        transcriptionByUrl.set(item.url, { status, result });
      });
      const completedCount = selected.filter((item) => transcriptionByUrl.get(item.url)?.status === 'completed').length;
      const partialCount = selected.filter((item) => transcriptionByUrl.get(item.url)?.status === 'partial').length;
      setTopicTranscriptionStatus(
        topicId,
        `转录进度 ${completedCount}/${selected.length} · 仅正文 ${partialCount} · OCR 待处理 ${pendingOcr} · 脚本待处理 ${pendingScript}`,
      );
      loadTopicItems(topicId, topicPages[topicId] || 1);
      if (!['completed', 'cancelled', 'failed'].includes(task.status) || pendingOcr > 0 || pendingScript > 0) {
        window.setTimeout(() => pollInlineTranscription(topicId, taskId, selected), 1500);
        return;
      }
      Array.from(selectedRadarItems.entries()).forEach(([key, item]) => {
        if (item.topicId === topicId) selectedRadarItems.delete(key);
      });
      setTopicTranscriptionStatus(
        topicId,
        task.status === 'failed'
          ? `转录失败：${task.message || (task.errors || []).join('；') || '任务执行失败'}`
          : `完整 ${completedCount} · 仅正文 ${partialCount} · 共 ${selected.length} 条（仅正文=有发布文案，但脚本/OCR 未拿到）`,
        task.status === 'failed' ? 'error' : 'ok',
      );
      loadTopicItems(topicId, topicPages[topicId] || 1);
    } catch (e) {
      setTopicTranscriptionStatus(topicId, e.message, 'error');
    }
  }

  function transcribeSingleItem(topicId, item) {
    selectedRadarItems.set(`${topicId}:${item.url}`, { ...item, topicId });
    updateSelectionBar(topicId);
    startSelectedTranscription(topicId);
  }

  // ---------------------------------------------------------------------
  // Shell + sub tabs
  // ---------------------------------------------------------------------

  function renderShell() {
    const root = document.getElementById('intelApp');
    root.innerHTML = '';
    root.appendChild(renderStatusBar());
    root.appendChild(renderIntelSubTabs());
    root.appendChild(el('div', { id: 'intelTabTopics', class: 'intel-tab-panel' }));
    root.appendChild(el('div', { id: 'intelTabMining', class: 'intel-tab-panel', hidden: 'hidden' }));
    root.appendChild(el('div', { id: 'intelTabAssets', class: 'intel-tab-panel', hidden: 'hidden' }));
    renderTopicsTab();
    renderMiningTab();
    renderAssetsTab();
    switchIntelTab('topics');
    refreshLoginStatus();
  }

  function renderIntelSubTabs() {
    const bar = el('nav', {
      class: 'intel-subtabs',
      style: 'display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;',
    });
    [
      ['topics', '1 获取依据'],
      ['mining', '2 选题分析'],
      ['assets', '3 语料资产'],
    ].forEach(([id, label]) => {
      bar.appendChild(
        el('button', {
          type: 'button',
          class: 'platform-tab intel-subtab',
          'data-intel-tab': id,
          onclick: () => switchIntelTab(id),
        }, [label])
      );
    });
    return bar;
  }

  function switchIntelTab(tab) {
    currentIntelTab = tab;
    document.querySelectorAll('.intel-subtab').forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-intel-tab') === tab);
    });
    document.getElementById('intelTabTopics').hidden = tab !== 'topics';
    document.getElementById('intelTabMining').hidden = tab !== 'mining';
    document.getElementById('intelTabAssets').hidden = tab !== 'assets';
    if (tab === 'mining') {
      loadCorpusAnalysis();
      loadMiningInsights();
      loadBenchmark();
    }
    if (tab === 'assets') {
      loadTracked();
      loadAssets();
    }
  }

  function renderStatusBar() {
    return el('div', {
      style: 'display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:14px;padding:10px 14px;border-radius:12px;background:var(--panel-2);border:1px solid var(--border);',
    }, [
      el('span', { id: 'intelXhsStatus', class: 'hint', style: 'margin:0;' }, ['小红书：—']),
      el('button', {
        class: 'btn-secondary btn-small',
        id: 'intelXhsLoginBtn',
        type: 'button',
        onclick: triggerXhsLogin,
      }, ['登录小红书']),
      el('span', { id: 'intelChannelsStatus', class: 'hint', style: 'margin:0;' }, ['视频号：—']),
      el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: () => refreshLoginStatus({ force: true }),
      }, ['刷新状态']),
    ]);
  }

  async function refreshLoginStatus(opts) {
    const force = !!(opts && opts.force);
    const statusEl = document.getElementById('intelXhsStatus');
    const channelsEl = document.getElementById('intelChannelsStatus');
    if (!statusEl) return;
    const cachedOk = sessionStorage.getItem(XHS_LOGIN_OK_KEY) === '1';
    try {
      const resp = await fetch(force ? '/api/xhs/login-status?force=1' : '/api/xhs/login-status');
      const data = await resp.json();
      if (data.logged_in === true) {
        sessionStorage.setItem(XHS_LOGIN_OK_KEY, '1');
        sessionStorage.setItem(XHS_LOGIN_AT_KEY, String(Date.now()));
        statusEl.textContent = '小红书：已登录';
        statusEl.style.color = 'var(--ok)';
        statusEl.title = data.message || '';
      } else if (data.logged_in === false) {
        sessionStorage.removeItem(XHS_LOGIN_OK_KEY);
        sessionStorage.removeItem(XHS_LOGIN_AT_KEY);
        statusEl.textContent = '小红书：未登录';
        statusEl.style.color = 'var(--err)';
        statusEl.title = data.message || '请点击「登录小红书」';
      } else if (cachedOk || data.session_reusable) {
        statusEl.textContent = '小红书：会话可用';
        statusEl.style.color = 'var(--ok)';
        statusEl.title = data.message || data.reason || '';
      } else {
        statusEl.textContent = '小红书：状态未知';
        statusEl.style.color = 'var(--muted)';
        statusEl.title = data.message || data.reason || '';
      }
    } catch (e) {
      if (cachedOk) {
        statusEl.textContent = '小红书：会话可用';
        statusEl.style.color = 'var(--ok)';
        statusEl.title = e.message || '';
      } else {
        statusEl.textContent = '小红书：状态未知';
        statusEl.style.color = 'var(--muted)';
        statusEl.title = e.message || '';
      }
    }
    if (channelsEl) {
      try {
        const resp = await fetch('/api/channels/browser/status');
        const data = await resp.json();
        if (data.logged_in) {
          channelsEl.textContent = '视频号：会话就绪';
          channelsEl.style.color = 'var(--ok)';
        } else {
          channelsEl.textContent = '视频号：API 模式';
          channelsEl.style.color = 'var(--muted)';
        }
        channelsEl.title = data.message || '';
      } catch (e) {
        channelsEl.textContent = '视频号：—';
        channelsEl.style.color = 'var(--muted)';
        channelsEl.title = e.message || '';
      }
    }
  }

  async function triggerXhsLogin() {
    const btn = document.getElementById('intelXhsLoginBtn');
    const old = btn ? btn.textContent : '登录小红书';
    if (btn) {
      btn.disabled = true;
      btn.textContent = '打开中…';
    }
    try {
      const loginResp = await fetch('/api/xhs/login', { method: 'POST' });
      const r = await loginResp.json().catch(() => ({}));
      if (!loginResp.ok) throw new Error(r.detail || r.message || `触发失败 (${loginResp.status})`);
      sessionStorage.setItem('intel_xhs_login_opened_at', String(Date.now()));
      setTimeout(() => refreshLoginStatus(), 2500);
      alert(r.message || '已打开小红书主页，请在 Chrome 窗口完成登录。');
    } catch (e) {
      alert(`登录失败：${e.message}`);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = old;
      }
    }
  }


  // ---------------------------------------------------------------------
  // Tab: 爆款采集
  // ---------------------------------------------------------------------

  function renderManualTranscriptionSection() {
    const section = el('section', { class: 'panel', style: 'margin-top:14px' });
    section.appendChild(el('div', { class: 'panel-head' }, ['链接转录']));
    const body = el('div', { class: 'panel-body' });
    const platform = el('select', { id: 'intelManualPlatform', style: inputStyle('110px') }, [
      el('option', { value: 'xhs' }, ['小红书']),
      el('option', { value: 'channels' }, ['视频号']),
    ]);
    const links = el('textarea', {
      id: 'intelManualLinks',
      placeholder: '每行一个分享链接',
      style: 'min-height:70px;flex:1 1 420px;',
    });
    body.appendChild(el('div', { style: 'display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap;' }, [
      platform,
      links,
      el('label', {
        style: 'display:flex;flex-direction:column;gap:4px;font-size:11.5px;color:var(--muted);',
      }, [
        '转录模式',
        el('select', {
          id: 'intelManualExtractMode',
          style: compactInputStyle('140px'),
        }, [
          el('option', { value: 'full', selected: defaultTranscriptionMode === 'full' ? 'selected' : undefined }, ['完整（脚本+OCR）']),
          el('option', { value: 'simple', selected: defaultTranscriptionMode === 'simple' ? 'selected' : undefined }, ['简单（标题+文案）']),
        ]),
      ]),
      el('button', { class: 'btn-primary', onclick: startManualExtraction }, ['提取并转录']),
    ]));
    body.appendChild(el('p', { id: 'intelManualExtractMsg', class: 'hint', style: 'margin:8px 0 0;' }, []));
    body.appendChild(el('div', { id: 'intelManualResults', style: 'margin-top:8px;' }, []));
    section.appendChild(body);
    return section;
  }

  function renderTopicsTab() {
    const panel = document.getElementById('intelTabTopics');
    panel.innerHTML = '';
    const section = el('section', { class: 'panel' });
    section.appendChild(el('div', { class: 'panel-head' }, ['创建采集任务']));
    const body = el('div', { class: 'panel-body' });

    const nameInput = el('input', { id: 'intelTopicName', placeholder: '选题名称', style: inputStyle('160px') });
    const kwInput = el('input', { id: 'intelTopicKeywords', placeholder: '关键词，逗号分隔', style: inputStyle('220px') });
    const xhsCheck = el('input', { type: 'checkbox', id: 'intelTopicXhs', checked: 'checked' });
    const chCheck = el('input', { type: 'checkbox', id: 'intelTopicChannels' });
    body.appendChild(
      el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:8px;' }, [
        nameInput, kwInput,
        el('label', { class: 'checkbox-row', style: 'margin:0' }, [xhsCheck, ' 小红书']),
        el('label', { class: 'checkbox-row', style: 'margin:0' }, [chCheck, ' 视频号']),
        el('button', { class: 'btn-primary', onclick: createTopic }, ['创建并保存']),
      ])
    );

    const tplSelect = el('select', { id: 'intelTemplateSelect', style: inputStyle('180px') }, [
      el('option', { value: '' }, ['预设模板…']),
    ]);
    body.appendChild(
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;' }, [
        tplSelect,
        el('button', { class: 'btn-secondary btn-small', onclick: createFromTemplate }, ['从模板创建']),
        el('span', { id: 'intelTemplateHint', class: 'hint', style: 'margin:0;' }, []),
      ])
    );
    loadSearchTemplates(tplSelect);

    const limitInput = el('input', {
      id: 'intelTopicLimit',
      type: 'number',
      value: '20',
      min: '1',
      max: '200',
      style: compactInputStyle('72px'),
    });
    const intervalInput = el('input', {
      id: 'intelTopicInterval', type: 'number', value: '360', min: '15', style: compactInputStyle('72px'),
    });
    const searchModeSelect = el('select', {
      id: 'intelTopicSearchMode', style: compactInputStyle('120px'),
    }, [
      el('option', { value: 'combined' }, ['组合检索']),
      el('option', { value: 'separate' }, ['分别检索']),
    ]);
    const noteTypeSelect = el('select', {
      id: 'intelTopicNoteType', style: compactInputStyle('100px'),
    }, [
      el('option', { value: '' }, ['类型不限']),
      el('option', { value: '视频' }, ['视频']),
      el('option', { value: '图文' }, ['图文']),
    ]);
    const SORT_ROUND_OPTIONS = ['综合', '最新', '最多点赞', '最多评论', '最多收藏'];
    const sortWrap = el('div', { style: 'display:flex;gap:6px 10px;flex-wrap:wrap;' });
    SORT_ROUND_OPTIONS.forEach((label, idx) => {
      sortWrap.appendChild(
        el('label', { class: 'checkbox-row', style: 'margin:0;font-size:12px;' }, [
          el('input', { type: 'checkbox', class: 'intelTopicSortRound', value: label, checked: idx === 0 ? 'checked' : undefined }),
          ` ${label}`,
        ])
      );
    });
    const thresholdFields = [
      ['intelTopicMinLiked', '最低赞'],
      ['intelTopicMinCollected', '最低藏'],
      ['intelTopicMinComments', '最低评'],
      ['intelTopicMinViews', '最低浏览'],
    ].map(([id, label]) => el('label', {
      style: 'display:flex;align-items:center;gap:6px;font-size:12px;white-space:nowrap;',
    }, [
      label,
      el('input', { id, type: 'number', value: '0', min: '0', style: compactInputStyle('64px') }),
    ]));
    const advBody = el('div', {
      style: 'display:grid;grid-template-columns:1fr;gap:8px;padding:8px 0 0;',
    }, [
      el('div', {
        style: 'display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px 12px;align-items:end;',
      }, [
        el('label', { style: 'font-size:12px;' }, ['目标条数', el('div', {}, [limitInput])]),
        el('label', { style: 'font-size:12px;' }, ['间隔(分)', el('div', {}, [intervalInput])]),
        el('label', { style: 'font-size:12px;' }, ['关键词', el('div', {}, [searchModeSelect])]),
        el('label', { style: 'font-size:12px;' }, ['类型', el('div', {}, [noteTypeSelect])]),
      ]),
      el('div', {}, [
        el('div', { style: 'font-size:12px;font-weight:600;margin-bottom:4px;' }, ['排序轮次']),
        sortWrap,
      ]),
      el('div', {
        style: 'display:flex;gap:10px 16px;flex-wrap:wrap;align-items:center;padding-top:2px;',
      }, thresholdFields),
    ]);
    body.appendChild(makeFold('筛选与采集设置', advBody, { defaultOpen: false, compact: true }));
    body.appendChild(el('p', { id: 'intelTopicCreateMsg', class: 'hint', style: 'margin:0 0 12px' }, []));

    section.appendChild(body);
    panel.appendChild(section);

    const listSection = el('section', { class: 'panel', style: 'margin-top:14px' });
    listSection.appendChild(el('div', { class: 'panel-head' }, ['已保存的采集任务']));
    listSection.appendChild(el('div', { class: 'panel-body', id: 'intelTopicList' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    panel.appendChild(listSection);
    panel.appendChild(renderManualTranscriptionSection());
    loadTopics();
  }

  async function loadTopics() {
    const listEl = document.getElementById('intelTopicList');
    if (!listEl) return;
    try {
      const data = await api('/watch-topics');
      topics = data.items || [];
    } catch (e) {
      listEl.innerHTML = '';
      listEl.appendChild(el('p', { class: 'hint' }, [`加载失败：${e.message}`]));
      return;
    }
    renderTopicBlocks(listEl);
  }

  function renderTopicBlocks(listEl) {
    listEl.innerHTML = '';
    if (!topics.length) {
      listEl.appendChild(el('p', { class: 'hint' }, ['还没有选题，在上方创建一个。']));
      return;
    }
    topics.forEach((t) => listEl.appendChild(renderTopicBlock(t)));
  }

  function renderTopicBlock(t) {
    const platformsLabel = (t.platforms || []).map((p) => (p === 'xhs' ? '小红书' : '视频号')).join(' / ');
    const kwLabel = (t.keywords || []).join('、') || '-';
    const runMsg = t.last_run_message ? `${t.last_run_at || ''} · ${t.last_run_message}` : '尚未运行';
    const count = t.item_count || 0;
    const filters = t.filters || {};
    const thresholdParts = [
      (filters.search_mode || 'combined') === 'combined' && (t.keywords || []).length > 1 ? '组合检索' : '分别检索',
      filters.note_type || '类型不限',
      filters.min_liked ? `赞≥${filters.min_liked}` : '',
      filters.min_collected ? `藏≥${filters.min_collected}` : '',
      filters.min_comments ? `评≥${filters.min_comments}` : '',
      filters.min_views ? `浏览≥${filters.min_views}` : '',
    ].filter(Boolean);

    const block = el('div', {
      style: 'margin-bottom:12px;border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--panel);',
    });

    const head = el('div', { style: 'padding:12px 14px;background:var(--panel-2);' });
    head.appendChild(
      el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;' }, [
        el('div', { style: 'flex:1 1 200px;' }, [
          el('div', { style: 'font-size:16px;font-weight:700;margin-bottom:4px;' }, [t.name]),
          el('div', { class: 'hint', style: 'font-size:12.5px;' }, [
            `${platformsLabel} · ${kwLabel} · 抓取 ${t.limit_per_run || 20} 条 · ${thresholdParts.join(' · ')} · 已收录 ${count} 条`,
          ]),
          el('div', {
            class: 'hint',
            style: `font-size:12px;margin-top:4px;${isRunMessageWarning(t.last_run_message) ? 'color:var(--err);' : ''}`,
          }, [`最近运行：${runMsg}`]),
        ]),
        el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;' }, [
          el('button', { class: 'btn-primary btn-small', onclick: (ev) => runTopicNow(t.id, ev.currentTarget) }, ['运行一次']),
          el('button', { class: 'btn-secondary btn-small', onclick: () => exportTopicPack(t.id, t.name) }, ['导出选题包']),
          el('button', { class: 'btn-secondary btn-small', onclick: () => exportTopicExcel(t.id, t.name) }, ['导出 Excel']),
          el('button', { class: 'btn-secondary btn-small', onclick: () => toggleDirections(t.id) }, ['选题方向']),
          el('button', { class: 'btn-secondary btn-small', onclick: () => toggleTopic(t) }, [t.enabled ? '停用' : '启用']),
          el('button', { class: 'btn-danger btn-small', onclick: () => deleteTopic(t.id) }, ['删除']),
        ]),
      ])
    );
    block.appendChild(head);
    const runResult = topicRunResults.get(t.id);
    if (runResult?.stats) {
      const stats = runResult.stats;
      const resultBar = el('div', {
        style: 'display:flex;gap:6px;flex-wrap:wrap;padding:8px 14px;border-top:1px solid var(--border);background:var(--panel);',
      });
      [
        ['候选', stats.discovered, '平台本次返回的原始内容数'],
        ['通过门槛', stats.eligible, '达到内容类型和互动量要求的内容数'],
        ['去重', stats.duplicates, '与本轮其他结果重复的内容数'],
        ['新增', runResult.added, '首次进入当前资料库的内容数'],
        ['更新', runResult.updated, '已存在且指标被刷新过的内容数'],
        ['搜索轮次', stats.rounds_run, '实际执行的排序搜索次数'],
      ].forEach(([label, value, title]) => {
        resultBar.appendChild(el('span', {
          title,
          style: 'padding:3px 7px;border-radius:999px;background:var(--panel-2);font-size:11px;',
        }, [`${label} ${value || 0}`]));
      });
      block.appendChild(resultBar);
    }

    const dirsWrap = el('div', {
      id: `intelTopicDirs-${t.id}`,
      hidden: 'hidden',
      style: 'padding:10px 14px;border-top:1px solid var(--border);background:var(--panel);',
    });
    block.appendChild(dirsWrap);

    const itemsDetails = el('details', {
      class: 'intel-topic-items-fold',
      style: 'border-top:1px solid var(--border);',
    });
    const summary = el('summary', {
      style: 'padding:10px 14px;cursor:pointer;font-size:13px;font-weight:600;color:var(--accent);list-style:none;',
    }, [`▸ 查看爆款内容（${count} 条，每页 ${PAGE_SIZE} 条）`]);
    itemsDetails.appendChild(summary);

    const itemsWrap = el('div', { id: `intelTopicItems-${t.id}`, style: 'padding:0 14px 10px;' });
    const pagerWrap = el('div', {
      id: `intelTopicPager-${t.id}`,
      style: 'padding:0 14px 12px;display:flex;gap:8px;align-items:center;justify-content:flex-end;',
    });
    itemsDetails.appendChild(itemsWrap);
    itemsDetails.appendChild(pagerWrap);

    itemsDetails.addEventListener('toggle', () => {
      if (itemsDetails.open) {
        summary.textContent = `▾ 爆款内容（${count} 条）`;
        if (!itemsDetails.dataset.loaded) {
          loadTopicItems(t.id, topicPages[t.id] || 1);
          itemsDetails.dataset.loaded = '1';
        }
      } else {
        summary.textContent = `▸ 查看爆款内容（${count} 条，每页 ${PAGE_SIZE} 条）`;
      }
    });

    if (!count) {
      itemsWrap.appendChild(el('p', { class: 'hint', style: 'margin:0;' }, ['暂无爆款，先运行一次采集。']));
    }

    block.appendChild(itemsDetails);
    return block;
  }

  async function loadTopicItems(topicId, page) {
    topicPages[topicId] = page;
    const itemsEl = document.getElementById(`intelTopicItems-${topicId}`);
    const pagerEl = document.getElementById(`intelTopicPager-${topicId}`);
    if (!itemsEl) return;
    try {
      const filters = topicItemFilters[topicId] || {};
      const query = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
        sort_by: filters.sort_by || 'value',
      });
      if (filters.note_type) query.set('note_type', filters.note_type);
      if (filters.min_liked) query.set('min_liked', String(filters.min_liked));
      if (filters.keyword) query.set('keyword', filters.keyword);
      const data = await api(`/watch-topics/${topicId}/items?${query.toString()}`);
      renderTopicItemsTable(itemsEl, data, topicId);
      renderTopicPager(pagerEl, data, topicId);
    } catch (e) {
      itemsEl.innerHTML = '';
      itemsEl.appendChild(el('p', { class: 'hint', style: 'color:var(--err);' }, [`加载失败：${e.message}`]));
      if (pagerEl) pagerEl.innerHTML = '';
    }
  }

  function renderTopicItemsTable(container, data, topicId) {
    container.innerHTML = '';
    const items = data.items || [];
    container.appendChild(renderTopicItemFilters(topicId, items));
    if (!items.length) {
      container.appendChild(el('p', { class: 'hint' }, ['该选题暂无爆款。']));
      return;
    }
    const table = el('table', { class: 'show', style: 'width:100%;' });
    table.appendChild(
      el('thead', {}, [
        el('tr', {}, [
          el('th', { style: 'width:34px;' }, ['选']),
          el('th', { style: 'width:36px;' }, ['#']),
          el('th', { style: 'width:56px;' }, ['封面']),
          el('th', {}, ['标题 / 作者']),
          el('th', { style: 'width:72px;' }, ['内容类型']),
          el('th', { style: 'min-width:220px;' }, ['转 · 赞 · 评 · 播 · 搜 · 藏']),
          el('th', { style: 'width:88px;' }, ['操作']),
          el('th', { style: 'width:120px;' }, ['转录']),
        ]),
      ])
    );
    const tbody = el('tbody');
    const baseIdx = (data.page - 1) * data.page_size;
    items.forEach((item, idx) => {
      const itemKey = `${topicId}:${item.url}`;
      const liveTranscription = transcriptionByUrl.get(item.url);
      const transcription = liveTranscription || (item.transcription
        ? {
            status: item.transcription.status,
            label: item.transcription.label,
            text: item.transcription.text,
            has_script: item.transcription.has_script,
            has_ocr: item.transcription.has_ocr,
            has_desc_only: item.transcription.has_desc_only,
            script_source: item.transcription.script_source,
            progress: item.transcription.progress,
          }
        : null);
      const itemCheck = el('input', {
        type: 'checkbox',
        checked: selectedRadarItems.has(itemKey) ? 'checked' : undefined,
        'aria-label': `选择 ${item.title || item.url}`,
      });
      itemCheck.addEventListener('change', () => {
        if (itemCheck.checked) selectedRadarItems.set(itemKey, { ...item, topicId });
        else selectedRadarItems.delete(itemKey);
        updateSelectionBar(topicId);
      });
      const coverSource = extractedCoverUrl(transcription?.result) || proxiedImageUrl(item.cover_url);
      const coverCell = coverSource
        ? el('img', {
            src: coverSource,
            alt: item.title ? `${item.title}封面` : '内容封面',
            referrerpolicy: 'no-referrer',
            style: 'width:44px;height:44px;object-fit:cover;border-radius:6px;background:var(--panel-2);',
            onerror: (event) => {
              const image = event.currentTarget;
              image.style.display = 'none';
              const fallback = image.nextElementSibling;
              if (fallback) fallback.style.display = 'flex';
            },
          })
        : el('div', { style: 'width:44px;height:44px;border-radius:6px;background:var(--panel-2);font-size:10px;display:flex;align-items:center;justify-content:center;color:var(--muted);' }, ['图文']);
      const coverFallback = coverSource
        ? el('div', { style: 'display:none;width:44px;height:44px;border-radius:6px;background:var(--panel-2);font-size:10px;align-items:center;justify-content:center;color:var(--muted);' }, ['暂无封面'])
        : null;
      const statusLabel = transcriptionStatusLabel(item, liveTranscription || item.transcription, transcription?.result);
      const progressPct = transcriptionProgressPercent(item, liveTranscription || item.transcription, transcription?.result);
      const titleNode = item.url
        ? el('a', {
            href: item.url,
            target: '_blank',
            style: 'font-size:13px;max-width:300px;color:var(--accent);text-decoration:none;display:inline-block;',
          }, [item.title || '(无标题)'])
        : el('div', { style: 'font-size:13px;max-width:300px;' }, [item.title || '(无标题)']);
      tbody.appendChild(
        el('tr', {}, [
          el('td', {}, [itemCheck]),
          el('td', {}, [String(baseIdx + idx + 1)]),
          el('td', {}, [coverCell, coverFallback]),
          el('td', {}, [
            titleNode,
            el('div', { class: 'hint', style: 'font-size:11.5px;' }, [item.author || '-']),
          ]),
          el('td', { style: 'font-size:11.5px;' }, [item.content_type || '其他']),
          el('td', {}, [renderMetrics(item)]),
          el('td', {}, [
            item.platform === 'xhs'
              ? el('button', {
                  class: 'btn-secondary btn-small',
                  style: 'font-size:11px;padding:2px 6px;',
                  onclick: () => transcribeSingleItem(topicId, item),
                }, ['转录'])
              : el('span', { class: 'hint', style: 'font-size:11px;' }, ['—']),
          ]),
          el('td', {}, [
            el('div', {
              style: `font-size:11px;margin-bottom:4px;color:${
                /已完成/.test(statusLabel)
                  ? 'var(--ok)'
                  : (/仅正文/.test(statusLabel) || transcription?.status === 'partial')
                    ? '#d97706'
                    : (transcription?.status === 'failed' || /失败/.test(statusLabel))
                      ? 'var(--err)'
                      : 'var(--muted)'
              };`,
            }, [statusLabel]),
            progressPct != null
              ? el('div', {
                  style: 'height:4px;border-radius:999px;background:var(--panel-2);overflow:hidden;margin-bottom:5px;',
                  title: `进度 ${progressPct}%`,
                }, [
                  el('div', {
                    style: `height:100%;width:${progressPct}%;background:${
                      /已完成/.test(statusLabel)
                        ? 'var(--ok)'
                        : /仅正文/.test(statusLabel)
                          ? '#d97706'
                          : 'var(--accent)'
                    };transition:width .35s ease;`,
                  }),
                ])
              : null,
            el('button', {
              class: 'btn-secondary btn-small',
              type: 'button',
              style: 'font-size:11px;padding:2px 8px;',
              disabled: !(item.transcription?.text || transcription?.result?.video_script || transcription?.result?.image_ocr_text || transcription?.text) ? 'disabled' : undefined,
              onclick: () => showTranscriptionFloat(item, liveTranscription || item.transcription, transcription?.result),
            }, ['查看']),
          ]),
        ])
      );
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  function renderTopicItemFilters(topicId, pageItems) {
    const current = topicItemFilters[topicId] || {};
    const transcriptionStatus = topicTranscriptionStatus.get(topicId) || {};
    const sort = el('select', { style: inputStyle('130px'), 'aria-label': '结果排序' }, [
      ['value', '综合价值'],
      ['relevance', '相关度'],
      ['liked', '点赞数'],
      ['collected', '收藏数'],
      ['comments', '评论数'],
      ['recent', '最近收录'],
    ].map(([value, label]) => el('option', {
      value,
      selected: (current.sort_by || 'value') === value ? 'selected' : undefined,
    }, [label])));
    const type = el('select', { style: inputStyle('105px'), 'aria-label': '内容类型' }, [
      ['', '全部类型'],
      ['图文', '图文'],
      ['视频', '视频'],
    ].map(([value, label]) => el('option', {
      value,
      selected: (current.note_type || '') === value ? 'selected' : undefined,
    }, [label])));
    const minLiked = el('input', {
      type: 'number',
      min: '0',
      value: current.min_liked || '',
      placeholder: '最低赞',
      style: inputStyle('88px'),
      'aria-label': '最低点赞数',
    });
    const keyword = el('input', {
      value: current.keyword || '',
      placeholder: '筛标题/关键词',
      style: inputStyle('140px'),
      'aria-label': '筛选标题或关键词',
    });
    const apply = () => {
      topicItemFilters[topicId] = {
        sort_by: sort.value,
        note_type: type.value,
        min_liked: Number(minLiked.value || 0),
        keyword: keyword.value.trim(),
      };
      loadTopicItems(topicId, 1);
    };
    sort.addEventListener('change', apply);
    type.addEventListener('change', apply);
    minLiked.addEventListener('change', apply);
    keyword.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') apply();
    });
    const selectPage = () => {
      const shouldSelect = pageItems.some((item) => !selectedRadarItems.has(`${topicId}:${item.url}`));
      pageItems.forEach((item) => {
        const key = `${topicId}:${item.url}`;
        if (shouldSelect) selectedRadarItems.set(key, { ...item, topicId });
        else selectedRadarItems.delete(key);
      });
      loadTopicItems(topicId, topicPages[topicId] || 1);
    };
    const reset = () => {
      topicItemFilters[topicId] = {};
      loadTopicItems(topicId, 1);
    };
    return el('div', {
      style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0;padding:10px;border-radius:10px;background:var(--panel-2);',
    }, [
      el('span', { style: 'font-size:12px;font-weight:700;' }, ['结果筛选']),
      el('label', { style: 'display:flex;gap:5px;align-items:center;font-size:11.5px;color:var(--muted);' }, ['排序', sort]),
      el('label', { style: 'display:flex;gap:5px;align-items:center;font-size:11.5px;color:var(--muted);' }, ['类型', type]),
      el('label', { style: 'display:flex;gap:5px;align-items:center;font-size:11.5px;color:var(--muted);' }, ['点赞', minLiked]),
      el('label', { style: 'display:flex;gap:5px;align-items:center;font-size:11.5px;color:var(--muted);' }, ['搜索', keyword]),
      el('button', { class: 'btn-secondary btn-small', type: 'button', onclick: apply }, ['应用']),
      el('button', { class: 'btn-secondary btn-small', type: 'button', onclick: reset }, ['重置']),
      el('button', { class: 'btn-secondary btn-small', type: 'button', onclick: selectPage }, ['全选/取消本页']),
      el('span', {
        id: `intelTranscriptionStatus-${topicId}`,
        class: 'hint',
        style: `margin:0;font-size:11.5px;color:${transcriptionStatus.tone === 'ok' ? 'var(--ok)' : (transcriptionStatus.tone === 'error' ? 'var(--err)' : 'var(--muted)')};`,
      }, [transcriptionStatus.message || '']),
      el('span', { id: `intelSelectionCount-${topicId}`, class: 'hint', style: 'margin:0 0 0 auto;' }, [
        `已选 ${selectedForTopic(topicId).length} 条`,
      ]),
      el('label', {
        style: 'display:flex;gap:5px;align-items:center;font-size:11.5px;color:var(--muted);',
      }, [
        '转录模式',
        el('select', {
          id: `intelTranscribeMode-${topicId}`,
          style: compactInputStyle('138px'),
          onchange: (ev) => {
            const mode = ev.target.value === 'simple' ? 'simple' : 'full';
            topicTranscriptionMode[topicId] = mode;
            defaultTranscriptionMode = mode;
          },
        }, [
          el('option', {
            value: 'full',
            selected: (topicTranscriptionMode[topicId] || defaultTranscriptionMode) === 'full' ? 'selected' : undefined,
          }, ['完整（脚本+OCR）']),
          el('option', {
            value: 'simple',
            selected: (topicTranscriptionMode[topicId] || defaultTranscriptionMode) === 'simple' ? 'selected' : undefined,
          }, ['简单（标题+文案）']),
        ]),
      ]),
      el('button', {
        id: `intelTranscribeBtn-${topicId}`,
        class: 'btn-primary btn-small',
        type: 'button',
        disabled: selectedForTopic(topicId).length ? undefined : 'disabled',
        onclick: () => startSelectedTranscription(topicId),
      }, ['转录选中内容']),
    ]);
  }

  function selectedForTopic(topicId) {
    return Array.from(selectedRadarItems.values()).filter((item) => item.topicId === topicId);
  }

  function updateSelectionBar(topicId) {
    const count = selectedForTopic(topicId).length;
    const countEl = document.getElementById(`intelSelectionCount-${topicId}`);
    const button = document.getElementById(`intelTranscribeBtn-${topicId}`);
    if (countEl) countEl.textContent = `已选 ${count} 条`;
    if (button) button.disabled = count === 0;
  }

  async function startSelectedTranscription(topicId) {
    const selected = selectedForTopic(topicId);
    if (!selected.length) return;
    const modeSel = document.getElementById(`intelTranscribeMode-${topicId}`);
    const mode = (modeSel?.value || topicTranscriptionMode[topicId] || defaultTranscriptionMode) === 'simple'
      ? 'simple'
      : 'full';
    topicTranscriptionMode[topicId] = mode;
    defaultTranscriptionMode = mode;
    const button = document.getElementById(`intelTranscribeBtn-${topicId}`);
    if (button) {
      button.disabled = true;
      button.textContent = '启动中…';
    }
    try {
      const body = mode === 'simple'
        ? {
            urls: selected.map((item) => item.url),
            extract_mode: 'simple',
            transcribe_video: false,
            long_video: false,
            ocr_images: false,
            cache_images: false,
            accumulate: true,
          }
        : {
            urls: selected.map((item) => item.url),
            extract_mode: 'full',
            transcribe_video: true,
            long_video: true,
            ocr_images: true,
            cache_images: true,
            accumulate: true,
          };
      const resp = await fetch('/api/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `启动失败 (${resp.status})`);
      selected.forEach((item) => transcriptionByUrl.set(item.url, { status: 'running', extract_mode: mode }));
      setTopicTranscriptionStatus(
        topicId,
        mode === 'simple'
          ? `简单模式：提取标题+文案 ${selected.length} 条…`
          : `完整模式：原位转录 ${selected.length} 条…`,
      );
      loadTopicItems(topicId, topicPages[topicId] || 1);
      if (data.task?.id) pollInlineTranscription(topicId, data.task.id, selected);
    } catch (e) {
      setTopicTranscriptionStatus(topicId, `转录启动失败：${e.message}`, 'error');
    } finally {
      if (button) {
        button.textContent = '转录选中内容';
        updateSelectionBar(topicId);
      }
    }
  }

  function renderTopicPager(container, data, topicId) {
    if (!container) return;
    container.innerHTML = '';
    const total = data.total || 0;
    const totalPages = data.total_pages || 0;
    if (!total) return;
    const page = data.page || 1;
    if (totalPages <= 1) {
      container.appendChild(el('span', { class: 'hint', style: 'font-size:12px;' }, [`共 ${total} 条`]));
      return;
    }
    container.appendChild(el('span', { class: 'hint', style: 'font-size:12px;margin-right:auto;' }, [`共 ${total} 条`]));
    container.appendChild(el('button', { class: 'btn-secondary btn-small', disabled: page <= 1 ? 'disabled' : undefined, onclick: () => loadTopicItems(topicId, page - 1) }, ['上一页']));
    container.appendChild(el('span', { style: 'font-size:12.5px;min-width:64px;text-align:center;' }, [`${page} / ${totalPages}`]));
    container.appendChild(el('button', { class: 'btn-secondary btn-small', disabled: page >= totalPages ? 'disabled' : undefined, onclick: () => loadTopicItems(topicId, page + 1) }, ['下一页']));
  }

  async function createTopic() {
    const msgEl = document.getElementById('intelTopicCreateMsg');
    const name = document.getElementById('intelTopicName').value.trim();
    const keywords = document.getElementById('intelTopicKeywords').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    const platforms = [];
    if (document.getElementById('intelTopicXhs').checked) platforms.push('xhs');
    if (document.getElementById('intelTopicChannels').checked) platforms.push('channels');
    const filters = {
      min_liked: Number(document.getElementById('intelTopicMinLiked').value || 0),
      min_collected: Number(document.getElementById('intelTopicMinCollected').value || 0),
      min_comments: Number(document.getElementById('intelTopicMinComments').value || 0),
      min_views: Number(document.getElementById('intelTopicMinViews').value || 0),
      search_mode: document.getElementById('intelTopicSearchMode').value || 'combined',
      sort_rounds: Array.from(document.querySelectorAll('.intelTopicSortRound:checked')).map((x) => x.value),
      note_type: document.getElementById('intelTopicNoteType').value || '',
    };
    if (!name || !keywords.length || !platforms.length) {
      msgEl.textContent = '请填写名称、关键词，并选择平台';
      msgEl.style.color = 'var(--err)';
      return;
    }
    try {
      await api('/watch-topics', {
        method: 'POST',
        body: JSON.stringify({
          name, keywords, platforms,
          limit_per_run: Number(document.getElementById('intelTopicLimit').value || 20),
          interval_minutes: Number(document.getElementById('intelTopicInterval').value || 360),
          filters,
        }),
      });
      document.getElementById('intelTopicName').value = '';
      document.getElementById('intelTopicKeywords').value = '';
      msgEl.textContent = `已创建「${name}」`;
      msgEl.style.color = 'var(--ok)';
      await loadTopics();
    } catch (e) {
      msgEl.textContent = `创建失败：${e.message}`;
      msgEl.style.color = 'var(--err)';
    }
  }

  async function runTopicNow(topicId, btn) {
    const old = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '运行中…'; }
    try {
      // 登录只由后端在运行开头统一校验一次，前端不再重复探测，
      // 避免"已登录仍弹未登录"的多重判断冲突。
      const result = await api(`/watch-topics/${topicId}/run`, { method: 'POST' });
      topicPages[topicId] = 1;
      const details = document.querySelector(`#intelTopicItems-${topicId}`)?.closest('details');
      if (details) {
        delete details.dataset.loaded;
        if (details.open) loadTopicItems(topicId, 1);
      }
      topicRunResults.set(topicId, result);
      await loadTopics();
      // 登录入口只在顶栏「登录小红书」；运行一次不再打开登录页。
      if (result && result.login_required) {
        alert('需要先登录小红书。请点击上方「登录小红书」，在主页完成登录后再运行。');
      }
    } catch (e) {
      alert(`运行失败：${e.message}`);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = old; }
    }
  }

  async function toggleTopic(t) {
    try {
      await api(`/watch-topics/${t.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !t.enabled }) });
      await loadTopics();
    } catch (e) { alert(`更新失败：${e.message}`); }
  }

  async function deleteTopic(topicId) {
    if (!confirm('确定删除该选题？')) return;
    try {
      await api(`/watch-topics/${topicId}`, { method: 'DELETE' });
      delete topicPages[topicId];
      await loadTopics();
    } catch (e) { alert(`删除失败：${e.message}`); }
  }

  async function loadSearchTemplates(sel) {
    if (!sel) return;
    try {
      const data = await api('/templates/search-dimensions');
      (data.items || []).forEach((t) => sel.appendChild(el('option', { value: t.id }, [t.name])));
    } catch (e) { /* ignore */ }
  }

  async function createFromTemplate() {
    const sel = document.getElementById('intelTemplateSelect');
    const msgEl = document.getElementById('intelTopicCreateMsg');
    if (!sel?.value) { msgEl.textContent = '请选择模板'; return; }
    try {
      const data = await api('/watch-topics/from-template', { method: 'POST', body: JSON.stringify({ template_id: sel.value }) });
      msgEl.textContent = `已创建「${data.item.name}」`;
      sel.value = '';
      await loadTopics();
    } catch (e) { msgEl.textContent = `失败：${e.message}`; }
  }

  async function exportTopicPack(topicId, topicName) {
    try {
      const resp = await fetch(`${API}/watch-topics/${topicId}/export.md`);
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || `导出失败 (${resp.status})`);
      }
      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = `${topicName || '选题'}-选题包.md`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (e) {
      alert(`选题包导出失败：${e.message}`);
    }
  }

  async function exportTopicExcel(topicId, topicName) {
    try {
      const resp = await fetch(`${API}/watch-topics/${topicId}/export.xlsx`);
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || `导出失败 (${resp.status})`);
      }
      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = `${topicName || '选题'}-采集结果.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (e) {
      alert(`Excel 导出失败：${e.message}`);
    }
  }

  async function toggleDirections(topicId) {
    const box = document.getElementById(`intelTopicDirs-${topicId}`);
    if (!box) return;
    if (!box.hidden && box.dataset.loaded === '1') { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = '';
    box.appendChild(el('p', { class: 'hint' }, ['生成中…']));
    try {
      const data = await api(`/watch-topics/${topicId}/directions?limit=5`);
      box.innerHTML = '';
      (data.directions || []).forEach((d, i) => {
        box.appendChild(el('div', { style: 'margin-bottom:8px;padding:10px;border-radius:8px;background:var(--panel-2);' }, [
          el('div', { style: 'font-weight:600;' }, [`方向 ${i + 1}：${d.angle_name || d.content_type}`]),
          el('div', { class: 'hint', style: 'font-size:12px;' }, [d.mechanism]),
          el('div', { style: 'font-size:12.5px;margin-top:4px;color:var(--accent);' }, [`仿写：${d.suggested_title}`]),
        ]));
      });
      if (!(data.directions || []).length) box.appendChild(el('p', { class: 'hint' }, ['暂无方向，先采集爆款。']));
      box.dataset.loaded = '1';
    } catch (e) {
      box.innerHTML = '';
      box.appendChild(el('p', { class: 'hint', style: 'color:var(--err);' }, [e.message]));
    }
  }

  // ---------------------------------------------------------------------
  // Tab: 选题挖掘
  // ---------------------------------------------------------------------

  function renderMiningTab() {
    const panel = document.getElementById('intelTabMining');
    panel.innerHTML = '';

    const corpusSection = el('section', { class: 'panel' });
    corpusSection.appendChild(el('div', { class: 'panel-head' }, ['语料分析与创作选题']));
    const corpusBody = el('div', { class: 'panel-body' });
    const topicSel = el('select', {
      id: 'intelMiningTopic',
      style: inputStyle('220px'),
      onchange: () => {
        corpusBatch = 0;
        loadCorpusAnalysis();
        loadMiningInsights();
      },
    }, [el('option', { value: '' }, ['全部已转录语料'])]);
    corpusBody.appendChild(el('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;' }, [
      topicSel,
      el('input', {
        id: 'intelCreativeBrief',
        value: creativeBrief,
        placeholder: '创作需求：产品、热点事件、目标人群或传播目标',
        style: inputStyle('300px'),
      }),
      el('button', {
        class: 'btn-primary btn-small',
        onclick: () => {
          creativeBrief = document.getElementById('intelCreativeBrief')?.value.trim() || '';
          corpusBatch = 0;
          loadCorpusAnalysis();
        },
      }, ['按需求生成']),
      el('button', {
        class: 'btn-secondary btn-small',
        onclick: () => {
          loadCorpusAnalysis();
          loadMiningInsights();
          loadBenchmark();
        },
      }, ['刷新']),
      el('span', { id: 'intelCorpusNote', class: 'hint', style: 'margin:0;' }, []),
    ]));
    const llmFields = el('div', {
      style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;',
    }, [
      el('input', {
        id: 'intelLlmApiKey',
        type: 'text',
        placeholder: 'TokenHub API Key（sk-…）',
        autocomplete: 'off',
        style: inputStyle('280px'),
      }),
      el('select', {
        id: 'intelLlmModel',
        style: inputStyle('170px'),
      }, [
        el('option', { value: 'deepseek-v4-pro' }, ['deepseek-v4-pro']),
        el('option', { value: 'deepseek-v4-flash' }, ['deepseek-v4-flash']),
        el('option', { value: 'deepseek-v3.2' }, ['deepseek-v3.2']),
      ]),
      el('input', {
        id: 'intelLlmBaseUrl',
        type: 'text',
        placeholder: 'https://tokenhub.tencentmaas.com/v1',
        style: inputStyle('260px'),
      }),
      el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: () => testLlmSettings(),
      }, ['测试']),
      el('button', {
        class: 'btn-primary btn-small',
        type: 'button',
        onclick: () => saveLlmSettings(),
      }, ['保存']),
      el('span', { id: 'intelLlmStatus', class: 'hint', style: 'margin:0;' }, []),
    ]);
    corpusBody.appendChild(makeFold('TokenHub 密钥', llmFields, {
      defaultOpen: false,
      compact: true,
      wrapStyle: 'margin:0 0 8px;',
    }));
    loadLlmSettings();
    corpusBody.appendChild(el('div', { id: 'intelCorpusAnalysis' }, [
      el('p', { class: 'hint' }, ['加载中…']),
    ]));
    corpusSection.appendChild(corpusBody);
    panel.appendChild(corpusSection);

    const filterSection = el('section', { class: 'panel' });
    filterSection.style.marginTop = '14px';
    filterSection.appendChild(el('div', { class: 'panel-head' }, ['从依据生成创作选题']));
    const filterBody = el('div', { class: 'panel-body' });
    filterBody.appendChild(el('p', { id: 'intelMiningNote', class: 'hint', style: 'margin:0 0 8px;' }, []));
    filterBody.appendChild(el('div', { id: 'intelMiningAngles' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    filterSection.appendChild(filterBody);
    panel.appendChild(filterSection);


    const s2 = el('section', { class: 'panel', style: 'margin-top:14px' });
    s2.appendChild(el('div', { class: 'panel-head' }, ['跨选题对标']));
    s2.appendChild(el('div', { class: 'panel-body', id: 'intelBenchmarkTable' }, [el('p', { class: 'hint' }, ['—'])]));
    panel.appendChild(s2);

    populateMiningTopicSelect(topicSel);
  }

  async function startManualExtraction(event) {
    const platform = document.getElementById('intelManualPlatform')?.value || 'xhs';
    const input = document.getElementById('intelManualLinks');
    const msg = document.getElementById('intelManualExtractMsg');
    const text = input?.value.trim() || '';
    const requestedUrls = text.split('\n').map((line) => line.trim()).filter(Boolean);
    if (!text) {
      if (msg) msg.textContent = '请至少粘贴一个分享链接。';
      return;
    }
    const button = event?.currentTarget;
    if (button) {
      button.disabled = true;
      button.textContent = '启动中…';
    }
    try {
      const modeSel = document.getElementById('intelManualExtractMode');
      const mode = (modeSel?.value || defaultTranscriptionMode) === 'simple' ? 'simple' : 'full';
      defaultTranscriptionMode = mode;
      const endpoint = platform === 'channels' ? '/api/channels/extract' : '/api/extract';
      const body = platform === 'channels'
        ? {
            text,
            transcribe_video: mode === 'full',
            long_video: mode === 'full',
          }
        : mode === 'simple'
          ? {
              text,
              extract_mode: 'simple',
              transcribe_video: false,
              long_video: false,
              ocr_images: false,
              cache_images: false,
              accumulate: true,
            }
          : {
              text,
              extract_mode: 'full',
              transcribe_video: true,
              long_video: true,
              ocr_images: true,
              cache_images: true,
              accumulate: true,
            };
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `启动失败 (${resp.status})`);
      if (input) input.value = '';
      if (msg) {
        msg.textContent = mode === 'simple'
          ? `已启动${platform === 'channels' ? '视频号' : '小红书'}简单提取（标题+文案）。`
          : `已启动${platform === 'channels' ? '视频号' : '小红书'}完整提取与转录，结果将在下方原位更新。`;
        msg.style.color = 'var(--ok)';
      }
      if (data.accumulated) renderManualTranscriptionResults(data.accumulated, requestedUrls);
      pollManualTranscription(platform, data.task?.id || '', requestedUrls);
    } catch (e) {
      if (msg) {
        msg.textContent = `启动失败：${e.message}`;
        msg.style.color = 'var(--err)';
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = '提取并转录';
      }
    }
  }

  async function loadCorpusAnalysis() {
    const container = document.getElementById('intelCorpusAnalysis');
    if (!container) return;
    const topicId = document.getElementById('intelMiningTopic')?.value || '';
    try {
      const query = new URLSearchParams({ batch: String(corpusBatch) });
      if (topicId) query.set('topic_id', topicId);
      if (creativeBrief) query.set('brief', creativeBrief);
      const data = await api(`/corpus/analysis?${query.toString()}`);
      renderCorpusAnalysis(container, data);
      const note = document.getElementById('intelCorpusNote');
      if (note && data.corpus_sync) {
        note.textContent = `已入库 ${data.corpus_sync.total || 0} 条 · 详见「语料资产」`;
      }
    } catch (e) {
      container.innerHTML = '';
      container.appendChild(el('p', { class: 'hint', style: 'color:var(--err);' }, [`语料分析失败：${e.message}`]));
    }
  }

  async function loadLlmSettings() {
    const statusEl = document.getElementById('intelLlmStatus');
    const keyEl = document.getElementById('intelLlmApiKey');
    const modelEl = document.getElementById('intelLlmModel');
    const baseEl = document.getElementById('intelLlmBaseUrl');
    if (!statusEl) return;
    try {
      const data = await api('/llm/status');
      if (keyEl && data.api_key) keyEl.value = data.api_key;
      if (modelEl && data.model) modelEl.value = data.model;
      if (baseEl) baseEl.value = data.base_url || 'https://tokenhub.tencentmaas.com/v1';
      statusEl.textContent = data.configured
        ? `已配置 · ${data.provider || 'tokenhub'} · ${data.model || ''} · ${data.api_key_masked || ''}`
        : '未配置密钥';
      statusEl.style.color = data.configured ? '' : 'var(--err)';
    } catch (e) {
      statusEl.textContent = `读取失败：${e.message}`;
      statusEl.style.color = 'var(--err)';
    }
  }

  async function saveLlmSettings() {
    const statusEl = document.getElementById('intelLlmStatus');
    const keyEl = document.getElementById('intelLlmApiKey');
    const modelEl = document.getElementById('intelLlmModel');
    const baseEl = document.getElementById('intelLlmBaseUrl');
    const apiKey = keyEl?.value.trim() || '';
    const model = modelEl?.value || 'deepseek-v4-pro';
    const baseUrl = baseEl?.value.trim() || 'https://tokenhub.tencentmaas.com/v1';
    if (!apiKey) {
      alert('请先填写 API Key');
      return;
    }
    if (statusEl) statusEl.textContent = '保存中…';
    try {
      const data = await api('/llm/config', {
        method: 'POST',
        body: JSON.stringify({ api_key: apiKey, model, base_url: baseUrl }),
      });
      if (baseEl && data.base_url) baseEl.value = data.base_url;
      if (statusEl) {
        statusEl.textContent = `已保存 · ${data.provider || 'tokenhub'} · ${data.model || model} · ${data.api_key_masked || ''}`;
        statusEl.style.color = '#059669';
      }
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = `保存失败：${e.message}`;
        statusEl.style.color = 'var(--err)';
      }
      alert(`保存失败：${e.message}`);
    }
  }

  async function testLlmSettings() {
    const statusEl = document.getElementById('intelLlmStatus');
    const keyEl = document.getElementById('intelLlmApiKey');
    const modelEl = document.getElementById('intelLlmModel');
    const baseEl = document.getElementById('intelLlmBaseUrl');
    const apiKey = keyEl?.value.trim() || '';
    const model = modelEl?.value || 'deepseek-v4-pro';
    const baseUrl = baseEl?.value.trim() || 'https://tokenhub.tencentmaas.com/v1';
    if (statusEl) statusEl.textContent = '测试中…';
    try {
      const data = await api('/llm/test', {
        method: 'POST',
        body: JSON.stringify({ api_key: apiKey || null, model, base_url: baseUrl }),
      });
      if (data.ok) {
        if (statusEl) {
          statusEl.textContent = `连接成功 · ${data.model} · ${data.reply || 'ok'}`;
          statusEl.style.color = '#059669';
        }
      } else {
        const err = data.error || '未知错误';
        if (statusEl) {
          statusEl.textContent = /401|Authentication|invalid/i.test(err)
            ? '鉴权失败：请确认是 TokenHub 密钥，且 base_url 为 tokenhub.tencentmaas.com/v1'
            : `失败：${err.slice(0, 140)}`;
          statusEl.style.color = 'var(--err)';
        }
      }
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = `测试失败：${e.message}`;
        statusEl.style.color = 'var(--err)';
      }
    }
  }

  function cooccurrenceEdgeWidth(count, maxCount) {
    const ratio = Math.max(0, Math.min(1, Number(count || 0) / Math.max(1, maxCount)));
    // 次数越多线越粗，但上限受控，避免最粗线抢画面
    return 0.55 + Math.sqrt(ratio) * 2.45;
  }

  function renderCooccurrenceNetwork(container, pairs, terms) {
    const termItems = (terms || []).slice(0, 24);
    const nodeNames = termItems.map((item) => item.term);
    const nodeSet = new Set(nodeNames);
    const termCounts = new Map(termItems.map((item) => [item.term, Number(item.count || 0)]));
    const clusterByName = new Map(termItems.map((item) => [item.term, Number(item.cluster || 0)]));
    const clusterColors = ['#3977f6', '#16a394', '#8b5cf6', '#f59e42'];
    const usablePairs = (pairs || []).filter(
      (pair) => pair.source && pair.target && nodeSet.has(pair.source) && nodeSet.has(pair.target)
    );
    if (!nodeNames.length) {
      container.appendChild(el('p', { class: 'hint', style: 'margin:0;' }, ['样本较少，暂未形成稳定共现关系。']));
      return;
    }
    const scores = new Map();
    termItems.forEach((item) => scores.set(item.term, Number(item.relevance || item.count || 1)));
    usablePairs.forEach((pair) => {
      const count = Number(pair.count || 0);
      scores.set(pair.source, (scores.get(pair.source) || 0) + count);
      scores.set(pair.target, (scores.get(pair.target) || 0) + count);
    });
    const width = 600;
    const height = 340;
    const centerX = width / 2;
    const centerY = height / 2;
    const positions = new Map();
    const ringSizes = nodeNames.length > 20
      ? [Math.min(6, nodeNames.length), Math.min(8, Math.max(0, nodeNames.length - 6)), Math.max(0, nodeNames.length - 14)]
      : (nodeNames.length > 10 ? [Math.ceil(nodeNames.length * .4), Math.floor(nodeNames.length * .6)] : [nodeNames.length]);
    const ringRadii = ringSizes.length === 3 ? [52, 102, 148] : (ringSizes.length === 2 ? [68, 132] : [112]);
    let offset = 0;
    ringSizes.forEach((ringCount, ring) => {
      nodeNames.slice(offset, offset + ringCount).forEach((name, index) => {
        const angle = -Math.PI / 2 + (index / Math.max(1, ringCount)) * Math.PI * 2;
        positions.set(name, {
          x: centerX + Math.cos(angle) * ringRadii[ring],
          y: centerY + Math.sin(angle) * ringRadii[ring],
        });
      });
      offset += ringCount;
    });

    const selected = new Set();
    const dragState = { active: null, offsetX: 0, offsetY: 0, moved: false, startX: 0, startY: 0 };
    container.style.position = 'relative';
    const tooltip = el('div', {
      style: 'display:none;position:fixed;z-index:30;padding:6px 9px;border-radius:8px;background:#183052;color:white;font-size:11.5px;pointer-events:none;box-shadow:0 6px 18px rgba(0,0,0,.18);',
    });
    container.appendChild(tooltip);
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', '词语共现关系网络，可点击词语进行多选高亮');
    svg.style.cssText = 'width:100%;height:340px;display:block;border-radius:8px;background:var(--panel-2);';
    const edgeEls = [];
    const nodeEls = new Map();
    const maxPairCount = Math.max(1, ...usablePairs.map((pair) => Number(pair.count || 0)));
    const maxScore = Math.max(1, ...scores.values());

    usablePairs.forEach((pair) => {
      const from = positions.get(pair.source);
      const to = positions.get(pair.target);
      const line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', from.x);
      line.setAttribute('y1', from.y);
      line.setAttribute('x2', to.x);
      line.setAttribute('y2', to.y);
      const sameCluster = clusterByName.get(pair.source) === clusterByName.get(pair.target);
      line.setAttribute('stroke', sameCluster ? clusterColors[clusterByName.get(pair.source) % clusterColors.length] : '#a9b8cc');
      line.setAttribute('stroke-opacity', sameCluster ? '.32' : '.18');
      const edgeWidth = cooccurrenceEdgeWidth(pair.count, maxPairCount);
      line.setAttribute('stroke-width', String(edgeWidth));
      svg.appendChild(line);
      edgeEls.push({ line, pair, edgeWidth });
    });

    const updateHighlight = () => {
      const neighbors = new Set();
      usablePairs.forEach((pair) => {
        if (selected.has(pair.source)) neighbors.add(pair.target);
        if (selected.has(pair.target)) neighbors.add(pair.source);
      });
      nodeEls.forEach(({ group, circle, baseColor }, name) => {
        const isSelected = selected.has(name);
        const isNeighbor = neighbors.has(name);
        group.style.opacity = !selected.size || isSelected ? '1' : (isNeighbor ? '.68' : '.2');
        circle.setAttribute('fill', isSelected ? '#ff8a3d' : baseColor);
        circle.setAttribute('stroke-width', isSelected ? '4' : '2');
      });

      edgeEls.forEach(({ line, pair, edgeWidth }) => {
        const active = selected.has(pair.source) || selected.has(pair.target);
        const sameCluster = clusterByName.get(pair.source) === clusterByName.get(pair.target);
        const baseColor = sameCluster ? clusterColors[clusterByName.get(pair.source) % clusterColors.length] : '#a9b8cc';
        line.setAttribute('stroke', selected.size && active ? '#ff8a3d' : baseColor);
        line.setAttribute('stroke-opacity', selected.size ? (active ? '.92' : '.05') : (sameCluster ? '.32' : '.18'));
        line.setAttribute('stroke-width', String(selected.size && active ? edgeWidth + 0.6 : edgeWidth));
      });
      status.textContent = selected.size
        ? `已高亮：${Array.from(selected).join('、')}`
        : `共 ${nodeNames.length} 个相关关键词 · 悬浮查看词频，点击可多选高亮`;
      clearButton.hidden = selected.size === 0;
    };
    const toggleSelection = (name) => {
      if (selected.has(name)) selected.delete(name);
      else selected.add(name);
      updateHighlight();
    };

    nodeNames.forEach((name) => {
      const pos = positions.get(name);
      const group = document.createElementNS(ns, 'g');
      group.setAttribute('role', 'button');
      group.setAttribute('tabindex', '0');
      group.setAttribute('aria-label', `${name}，词频 ${termCounts.get(name) || 0}`);
      group.style.cursor = 'pointer';
      const title = document.createElementNS(ns, 'title');
      title.textContent = `${name} · 词频 ${termCounts.get(name) || 0}`;
      const circle = document.createElementNS(ns, 'circle');
      const nodeRadius = 10 + scores.get(name) / maxScore * 9;
      circle.setAttribute('cx', pos.x);
      circle.setAttribute('cy', pos.y);
      circle.setAttribute('r', nodeRadius);
      circle.setAttribute('data-base-r', String(nodeRadius));
      const baseColor = clusterColors[clusterByName.get(name) % clusterColors.length];
      circle.setAttribute('fill', baseColor);
      circle.setAttribute('stroke', 'white');
      circle.setAttribute('stroke-width', '2');
      circle.style.pointerEvents = 'auto';
      const text = document.createElementNS(ns, 'text');
      text.setAttribute('x', pos.x);
      text.setAttribute('y', pos.y + nodeRadius + 14);
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('font-size', '11');
      text.setAttribute('font-weight', '600');
      text.setAttribute('fill', 'currentColor');
      text.style.pointerEvents = 'none';
      text.textContent = name;

      group.addEventListener('mousedown', (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        dragState.active = name;
        dragState.moved = false;
        dragState.startX = event.clientX;
        dragState.startY = event.clientY;
        const rect = svg.getBoundingClientRect();
        const scaleX = width / rect.width;
        const scaleY = height / rect.height;
        dragState.offsetX = event.clientX * scaleX - pos.x;
        dragState.offsetY = event.clientY * scaleY - pos.y;
        group.style.cursor = 'grabbing';
      });
      window.addEventListener('mousemove', (event) => {
        if (dragState.active !== name) return;
        const rect = svg.getBoundingClientRect();
        const scaleX = width / rect.width;
        const scaleY = height / rect.height;
        if (Math.abs(event.clientX - dragState.startX) > 3 || Math.abs(event.clientY - dragState.startY) > 3) {
          dragState.moved = true;
        }
        const nx = event.clientX * scaleX - dragState.offsetX;
        const ny = event.clientY * scaleY - dragState.offsetY;
        positions.set(name, { x: nx, y: ny });
        circle.setAttribute('cx', nx);
        circle.setAttribute('cy', ny);
        text.setAttribute('x', nx);
        text.setAttribute('y', ny + nodeRadius + 14);
        edgeEls.forEach(({ line, pair }) => {
          if (pair.source !== name && pair.target !== name) return;
          const from = positions.get(pair.source);
          const to = positions.get(pair.target);
          line.setAttribute('x1', from.x);
          line.setAttribute('y1', from.y);
          line.setAttribute('x2', to.x);
          line.setAttribute('y2', to.y);
        });
      });
      window.addEventListener('mouseup', () => {
        if (dragState.active === name) {
          dragState.active = null;
          group.style.cursor = 'grab';
        }
      });
      group.style.cursor = 'grab';

      group.addEventListener('click', (event) => {
        if (dragState.moved) return;
        toggleSelection(name);
      });
      group.addEventListener('mouseenter', () => {
        status.textContent = `${name} · 词频 ${termCounts.get(name) || 0}`;
        tooltip.textContent = `${name} · 词频 ${termCounts.get(name) || 0}`;
        tooltip.style.display = 'block';
      });
      group.addEventListener('mousemove', (event) => {
        tooltip.style.left = `${event.clientX + 12}px`;
        tooltip.style.top = `${event.clientY + 12}px`;
      });
      group.addEventListener('mouseleave', () => {
        status.textContent = selected.size ? `已高亮：${Array.from(selected).join('、')}` : '悬浮查看词频，点击可多选高亮';
        tooltip.style.display = 'none';
      });
      group.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          toggleSelection(name);
        }
      });
      group.appendChild(title);
      group.appendChild(circle);
      group.appendChild(text);
      svg.appendChild(group);
      nodeEls.set(name, { group, circle, baseColor });
    });

    const status = el('span', { class: 'hint', style: 'margin:0;font-size:11.5px;' }, [
      `共 ${nodeNames.length} 个相关关键词 · 悬浮查看词频，点击可多选高亮`,
    ]);
    const clearButton = el('button', {
      class: 'btn-secondary btn-small',
      type: 'button',
      hidden: 'hidden',
      onclick: () => {
        selected.clear();
        updateHighlight();
      },
    }, ['清除高亮']);
    container.appendChild(el('div', {
      style: 'display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;',
    }, [status, clearButton]));
    container.appendChild(svg);
  }

  function renderCorpusAnalysis(container, data) {
    container.innerHTML = '';
    const summary = data.summary || {};
    const stats = el('div', {
      style: 'display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:14px;',
    });
    [
      ['有效语料', summary.items || 0],
      ['视频脚本', summary.with_script || 0],
      ['图片 OCR', summary.with_ocr || 0],
      ['小红书 / 视频号', `${summary.xhs || 0} / ${summary.channels || 0}`],
      ['视频 / 图文', `${summary.videos || 0} / ${summary.graphics || 0}`],
    ].forEach(([label, value]) => {
      stats.appendChild(el('div', {
        style: 'padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--panel-2);',
      }, [
        el('div', { style: 'font-size:11.5px;color:var(--muted);' }, [label]),
        el('div', { style: 'font-size:20px;font-weight:700;margin-top:3px;' }, [String(value)]),
      ]));
    });
    container.appendChild(stats);

    if (!summary.items) {
      container.appendChild(el('p', { class: 'hint' }, ['暂无匹配语料。请先在“获取选题与依据”中勾选内容并启动转录。']));
      return;
    }

    const analysisGrid = el('div', {
      style: 'display:grid;grid-template-columns:minmax(0,1.45fr) minmax(260px,.75fr);gap:12px;align-items:start;',
    });
    const relations = el('div', {
      style: 'padding:12px;border:1px solid var(--border);border-radius:10px;',
    }, [el('div', { style: 'font-weight:700;margin-bottom:8px;' }, ['相关关键词与整体共现网络'])]);
    const pairs = data.cooccurrence || [];
    renderCooccurrenceNetwork(relations, pairs, data.top_terms || []);
    analysisGrid.appendChild(relations);
    const insights = el('div', {
      style: 'display:flex;flex-direction:column;gap:10px;',
    });
    const suggestions = el('div', {
      style: 'padding:11px;border:1px solid rgba(47,123,255,.3);border-radius:10px;background:rgba(47,123,255,.05);',
    });
    const llmFailHint = (() => {
      const err = String(data.llm_error || '');
      if (!err) return '规则兜底';
      if (/401|Authentication|invalid/i.test(err)) return '密钥无效·规则兜底';
      return '规则兜底';
    })();
    const miner = data.topic_miner || {};
    const minerBadge = miner.installed
      ? el('span', {
          class: 'hint',
          style: 'margin:0;padding:2px 8px;border-radius:6px;background:rgba(37,99,235,.1);color:#2563eb;font-size:11px;font-weight:600;',
          title: `选题框架 ${miner.skill || 'viral-topic-miner'} · ${miner.profile || '百度搭子/秒哒/热点弱偏好'}`,
        }, ['选题雷达'])
      : el('span', {
          class: 'hint',
          style: 'margin:0;padding:2px 8px;border-radius:6px;background:rgba(100,116,139,.1);color:#64748b;font-size:11px;',
          title: miner.error || 'viral-topic-miner 未检测到',
        }, ['选题框架待装']);
    const llmBadge = data.llm_used
      ? el('span', {
          class: 'hint',
          style: 'margin:0;padding:2px 8px;border-radius:6px;background:rgba(16,185,129,.12);color:#059669;font-size:11px;font-weight:600;',
          title: '由腾讯云 TokenHub · DeepSeek 生成，并注入 viral-topic-miner；百度搭子/秒哒/热点仅作弱偏好',
        }, ['TokenHub'])
      : (data.brief
        ? el('span', {
            class: 'hint',
            style: 'margin:0;padding:2px 8px;border-radius:6px;background:rgba(100,116,139,.1);color:#64748b;font-size:11px;',
            title: data.llm_error || '未调用大模型',
          }, [llmFailHint])
        : null);
    suggestions.appendChild(el('div', {
      style: 'display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px;',
    }, [
      el('div', { style: 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;' }, [
        el('div', { style: 'font-weight:700;' }, ['可直接进入创作的选题']),
        minerBadge,
        llmBadge,
      ]),
      el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: () => {
          corpusBatch += 1;
          loadCorpusAnalysis();
        },
      }, ['换一批']),
    ]));
    const savedTitles = new Set((data.saved_topics || []).map((item) => item.title));
    latestSuggestedTopics = (data.suggested_topics || []).slice(0, 6).map((raw, index) => {
      const topic = typeof raw === 'string'
        ? { title: raw, angle_id: '', angle_name: '', angle: '', evidence: [] }
        : raw;
      return { ...topic, index: index + 1 };
    });
    const topicList = el('div', { id: 'intelSuggestedTopicList' });
    latestSuggestedTopics.forEach((topic, idx) => {
      const saveButton = el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        disabled: savedTitles.has(topic.title) ? 'disabled' : undefined,
        onclick: (ev) => {
          ev.stopPropagation();
          saveCreativeTopic(topic.title, data.topic_id || '', data.batch || 0, saveButton);
        },
      }, [savedTitles.has(topic.title) ? '已保存' : '保存']);
      const regenButton = el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: (ev) => {
          ev.stopPropagation();
          const briefEl = document.getElementById('intelCreativeBrief');
          const seed = [
            topic.title,
            topic.angle_name ? `维度：${topic.angle_name}` : '',
            topic.angle || '',
          ].filter(Boolean).join('；');
          if (briefEl) briefEl.value = seed.slice(0, 120);
          creativeBrief = (briefEl?.value || seed).trim();
          corpusBatch = 0;
          loadCorpusAnalysis();
        },
      }, ['据此再生成']);
      topicList.appendChild(el('div', {
        role: 'button',
        tabindex: '0',
        title: '点击跳到下方对应维度，查看依据与写法',
        style: [
          'display:flex;align-items:flex-start;gap:8px;padding:8px 10px;',
          'border-bottom:1px dashed var(--border);cursor:pointer;',
          'border-left:3px solid transparent;',
        ].join(''),
        onclick: () => jumpToAngleTopic(topic),
        'data-topic-idx': String(idx),
      }, [
        el('div', { style: 'flex:1;min-width:0;' }, [
          el('div', { style: 'font-size:13px;font-weight:700;line-height:1.4;' }, [`${topic.index}. ${topic.title}`]),
          topic.angle_name
            ? el('div', { class: 'hint', style: 'font-size:11px;margin-top:2px;' }, [`↓ ${topic.angle_name}`])
            : null,
        ]),
        el('div', { style: 'display:flex;gap:6px;flex-shrink:0;' }, [regenButton, saveButton]),
      ]));
    });
    suggestions.appendChild(topicList);
    if (!latestSuggestedTopics.length) {
      suggestions.appendChild(el('p', { class: 'hint', style: 'margin:8px 0 0;' }, ['暂无选题，先填写创作需求或刷新分析。']));
    }
    // refresh bottom mapping with latest titles
    loadMiningInsights();
    const saved = data.saved_topics || [];
    if (saved.length) {
      const savedList = el('div', {});
      saved.slice(0, 30).forEach((item) => {
        savedList.appendChild(el('div', {
          style: 'display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12.5px;',
        }, [
          el('span', { style: 'flex:1;' }, [item.title]),
          el('button', {
            class: 'btn-secondary btn-small',
            type: 'button',
            onclick: async () => {
              await api(`/corpus/topics/${item.id}`, { method: 'DELETE' });
              loadCorpusAnalysis();
            },
          }, ['移除']),
        ]));
      });
      suggestions.appendChild(makeFold(`已保存选题（${saved.length}）`, savedList, {
        defaultOpen: false,
        compact: true,
        wrapStyle: 'margin-top:8px;',
      }));
    }
    insights.appendChild(suggestions);
    analysisGrid.appendChild(insights);
    container.appendChild(analysisGrid);
  }

  function jumpToAngleTopic(topic) {
    const target = document.getElementById(`intelAngleTopic-${topic.index}`);
    if (!target) {
      const anglesEl = document.getElementById('intelMiningAngles');
      anglesEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (target.tagName === 'DETAILS') target.open = true;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.remove('flash-highlight');
    // force reflow so the animation can replay on repeated clicks
    void target.offsetWidth;
    target.classList.add('flash-highlight');
  }

  function buildTopicDetailContent(topic) {
    const evidence = (topic.evidence || []).filter((ev) => ev && (ev.title || ev.url));
    const detailKids = [
      topic.angle
        ? el('div', { style: 'margin:4px 0;' }, [
          el('span', { style: 'font-weight:600;color:var(--text);' }, ['切入：']),
          topic.angle,
        ])
        : null,
      topic.structure
        ? el('div', { style: 'margin:4px 0;' }, [
          el('span', { style: 'font-weight:600;color:var(--text);' }, ['写法：']),
          topic.structure,
        ])
        : null,
      topic.why_viral
        ? el('div', { style: 'margin:4px 0;' }, [
          el('span', { style: 'font-weight:600;color:var(--text);' }, ['为什么会爆：']),
          topic.why_viral,
        ])
        : null,
    ].filter(Boolean);
    const mj = topic.miner_judgment || null;
    if (mj && (mj.audience || mj.emotion || mj.scene || mj.grade)) {
      const gradeColors = {
        '优先押注': 'background:rgba(220,38,38,.1);color:#dc2626;',
        '小爆候选': 'background:rgba(234,88,12,.1);color:#ea580c;',
        '可做级': 'background:rgba(37,99,235,.1);color:#2563eb;',
        '入库级': 'background:rgba(100,116,139,.12);color:#64748b;',
      };
      const judgeKids = [
        el('div', { style: 'display:flex;align-items:center;gap:8px;margin-bottom:4px;' }, [
          el('span', { style: 'font-weight:600;color:var(--text);' }, ['选题判断']),
          mj.grade
            ? el('span', {
              style: `padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;${gradeColors[mj.grade] || gradeColors['入库级']}`,
              title: mj.grade_reason || '',
            }, [mj.grade])
            : null,
        ]),
        mj.audience ? el('div', { style: 'margin:2px 0;' }, [el('span', { style: 'font-weight:600;color:var(--text);' }, ['人群：']), mj.audience]) : null,
        mj.emotion ? el('div', { style: 'margin:2px 0;' }, [el('span', { style: 'font-weight:600;color:var(--text);' }, ['情绪/问题：']), mj.emotion]) : null,
        mj.scene ? el('div', { style: 'margin:2px 0;' }, [el('span', { style: 'font-weight:600;color:var(--text);' }, ['可拍场景：']), mj.scene]) : null,
        mj.grade_reason ? el('div', { style: 'margin:2px 0;' }, [el('span', { style: 'font-weight:600;color:var(--text);' }, ['评级理由：']), mj.grade_reason]) : null,
      ].filter(Boolean);
      detailKids.push(el('div', {
        style: 'margin-top:8px;padding:8px 10px;border-radius:8px;background:rgba(47,123,255,.06);',
      }, judgeKids));
    }
    if (evidence.length) {
      const evList = el('div', { style: 'margin-top:8px;' }, [
        el('div', { style: 'font-weight:600;margin-bottom:4px;color:var(--text);' }, ['依据爆款']),
      ]);
      evidence.slice(0, 3).forEach((ev) => {
        evList.appendChild(el('div', { style: 'padding:3px 0;font-size:12.5px;' }, [
          ev.url
            ? el('a', { href: ev.url, target: '_blank', rel: 'noopener' }, [ev.title || ev.url])
            : el('span', {}, [ev.title || '']),
          ev.liked_count
            ? el('span', { class: 'hint', style: 'margin-left:6px;' }, [`赞 ${fmtNum(ev.liked_count)}`])
            : null,
        ]));
      });
      detailKids.push(evList);
    }
    if (!detailKids.length) {
      return el('p', { class: 'hint', style: 'margin:4px 0 0;' }, ['该选题暂无依据说明。']);
    }
    return el('div', {
      style: 'margin-top:6px;line-height:1.55;font-size:12.5px;color:var(--muted);',
    }, detailKids);
  }

  function topicCopyKey(topic) {
    return `${topic.angle_id || topic.angle_name || ''}::${topic.title || topic.index}`;
  }

  function topicCopyState(topic) {
    const key = topicCopyKey(topic);
    if (!topicCopyStates.has(key)) {
      topicCopyStates.set(key, {
        draft: '',
        instruction: '',
        history: [],
        loading: false,
        error: '',
      });
    }
    return topicCopyStates.get(key);
  }

  function rerenderCopyWorkbench(topic) {
    const mount = document.getElementById(`intelCopyWorkbench-${topic.index}`);
    if (!mount) return;
    const replacement = buildCopyWorkbench(topic);
    mount.replaceWith(replacement);
  }

  async function requestTopicCopy(topic, instruction) {
    const state = topicCopyState(topic);
    if (state.loading) return;
    state.loading = true;
    state.error = '';
    state.instruction = instruction || '';
    rerenderCopyWorkbench(topic);
    try {
      const result = await api('/copywriting', {
        method: 'POST',
        body: JSON.stringify({
          topic,
          instruction: state.instruction,
          current_draft: state.draft,
          history: state.history.slice(-6),
        }),
      });
      if (state.instruction) {
        state.history.push({ role: 'user', content: state.instruction });
      }
      state.draft = result.copy || '';
      state.history.push({
        role: 'assistant',
        content: result.mode === 'revise' ? '已按要求完成整篇修改' : '已生成第一版完整文案',
      });
      state.instruction = '';
    } catch (e) {
      state.error = e.message || '生成失败';
    } finally {
      state.loading = false;
      rerenderCopyWorkbench(topic);
    }
  }

  function buildCopyWorkbench(topic) {
    const state = topicCopyState(topic);
    const root = el('aside', {
      id: `intelCopyWorkbench-${topic.index}`,
      class: 'intel-copy-workbench',
      'aria-label': `${topic.title} 文案工作台`,
    });
    const header = el('div', { class: 'intel-copy-head' }, [
      el('div', {}, [
        el('div', { class: 'intel-copy-title' }, ['完整文案']),
        state.draft
          ? el('span', { class: 'badge', style: 'font-size:10px;padding:2px 6px;' }, [
            `${state.draft.length} 字`,
          ])
          : null,
      ]),
      el('div', { style: 'display:flex;gap:6px;' }, [
        state.draft
          ? el('button', {
            class: 'btn-secondary btn-small',
            type: 'button',
            onclick: async () => {
              await navigator.clipboard.writeText(state.draft);
            },
          }, ['复制'])
          : null,
        el('button', {
          class: 'btn-primary btn-small',
          type: 'button',
          disabled: state.loading ? 'disabled' : undefined,
          onclick: () => requestTopicCopy(topic, ''),
        }, [state.loading ? '生成中…' : (state.draft ? '重新生成' : '生成文案')]),
      ]),
    ]);
    root.appendChild(header);

    const draft = el('textarea', {
      class: 'intel-copy-draft',
      placeholder: '点击「生成文案」，模型会结合当前选题、爆款判断与对应语料生成完整小红书文案。',
      disabled: state.loading ? 'disabled' : undefined,
      oninput: (ev) => { state.draft = ev.target.value; },
    });
    draft.value = state.draft;
    root.appendChild(draft);

    if (state.history.length) {
      const recent = state.history.slice(-4);
      root.appendChild(el('div', { class: 'intel-copy-history' }, recent.map((item) =>
        el('div', { class: `intel-copy-message ${item.role}` }, [item.content])
      )));
    }

    const instruction = el('textarea', {
      class: 'intel-copy-instruction',
      placeholder: state.draft
        ? '输入修改要求，例如：开头更抓人、压缩到 500 字、语气更像真实体验…'
        : '可选：先补充文案要求，例如目标人群、语气、字数…',
      disabled: state.loading ? 'disabled' : undefined,
      oninput: (ev) => { state.instruction = ev.target.value; },
      onkeydown: (ev) => {
        if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') {
          ev.preventDefault();
          requestTopicCopy(topic, ev.currentTarget.value.trim());
        }
      },
    });
    instruction.value = state.instruction;
    root.appendChild(el('div', { class: 'intel-copy-chat' }, [
      instruction,
      el('button', {
        class: 'btn-primary btn-small',
        type: 'button',
        disabled: state.loading ? 'disabled' : undefined,
        onclick: () => requestTopicCopy(topic, instruction.value.trim()),
      }, [state.draft ? '修改' : '生成']),
    ]));
    if (state.error) {
      root.appendChild(el('div', {
        role: 'alert',
        style: 'margin-top:6px;font-size:12px;color:var(--err);',
      }, [state.error]));
    }
    return root;
  }

  async function saveCreativeTopic(title, topicId, batch, button) {
    button.disabled = true;
    button.textContent = '保存中…';
    try {
      await api('/corpus/topics', {
        method: 'POST',
        body: JSON.stringify({ title, topic_id: topicId, batch }),
      });
      button.textContent = '已保存';
      loadCorpusAnalysis();
    } catch (e) {
      button.disabled = false;
      button.textContent = '重试';
      alert(`保存失败：${e.message}`);
    }
  }

  async function populateMiningTopicSelect(sel) {
    if (!sel) return;
    try {
      const data = await api('/watch-topics');
      (data.items || []).forEach((t) => {
        sel.appendChild(el('option', { value: t.id }, [t.name]));
      });
    } catch (e) { /* ignore */ }
  }

  const OPPORTUNITY_LABELS = { high: '蓝海（建议补采集）', medium: '可加强', covered: '已有覆盖' };

  async function loadMiningInsights() {
    const anglesEl = document.getElementById('intelMiningAngles');
    const noteEl = document.getElementById('intelMiningNote');
    const topicSel = document.getElementById('intelMiningTopic');
    if (!anglesEl) return;
    const topicId = topicSel?.value || '';
    const qs = topicId ? `?topic_id=${encodeURIComponent(topicId)}` : '';
    try {
      const healthResp = await fetch('/api/health');
      const health = await healthResp.json().catch(() => ({}));
      if (health.version && String(health.version).localeCompare('1.12.0', undefined, { numeric: true }) < 0) {
        anglesEl.innerHTML = '';
        anglesEl.appendChild(
          el('p', { class: 'hint', style: 'color:var(--err);' }, [
            `当前服务版本 v${health.version} 过旧，选题挖掘接口需要 v1.12.0+。请运行 ./open_app.sh 重启服务后刷新页面。`,
          ])
        );
        return;
      }
      const mining = await api(`/mining/insights${qs}`);
      if (noteEl) {
        noteEl.textContent = `${mining.scope} · 共 ${mining.total_items} 条爆款`;
      }
      renderMiningAngles(anglesEl, mining.angles || [], latestSuggestedTopics);
    } catch (e) {
      anglesEl.innerHTML = '';
      const msg = /404|Not Found/i.test(e.message)
        ? '接口不存在（Not Found）：服务可能未重启到 v1.12.0。请运行 ./open_app.sh 后强制刷新页面（Cmd+Shift+R）。'
        : `分析失败：${e.message}`;
      anglesEl.appendChild(el('p', { class: 'hint', style: 'color:var(--err);' }, [msg]));
    }
  }

  function renderMiningAngles(container, angles, suggestedTopics) {
    container.innerHTML = '';
    if (!angles.length) {
      container.appendChild(el('p', { class: 'hint' }, ['暂无数据，请先在「爆款采集」运行任务。']));
      return;
    }
    const mapped = Array.isArray(suggestedTopics) ? suggestedTopics : [];
    const byAngle = new Map();
    mapped.forEach((topic) => {
      const key = topic.angle_id || topic.angle_name || '';
      if (!byAngle.has(key)) byAngle.set(key, []);
      byAngle.get(key).push(topic);
    });
    const ordered = [...angles].sort((a, b) => {
      const aHit = (byAngle.get(a.id) || byAngle.get(a.name) || []).length;
      const bHit = (byAngle.get(b.id) || byAngle.get(b.name) || []).length;
      if (aHit !== bHit) return bHit - aHit;
      return (b.item_count || 0) - (a.item_count || 0);
    });
    const grid = el('div', { style: 'display:flex;flex-direction:column;gap:12px;' });
    ordered.forEach((a) => {
      const linked = byAngle.get(a.id) || byAngle.get(a.name) || [];
      if (mapped.length && !linked.length) return; // only show dimensions that correspond to top titles
      const card = el('div', {
        style: 'border:1px solid var(--border);border-radius:12px;padding:12px 14px;background:var(--panel);',
      });
      const head = el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;justify-content:space-between;margin-bottom:8px;' }, [
        el('div', {}, [
          el('div', { style: 'font-size:15px;font-weight:700;' }, [a.name]),
          el('div', { class: 'hint', style: 'font-size:12px;margin-top:2px;' }, [a.description]),
        ]),
        el('div', { style: 'text-align:right;font-size:12px;color:var(--muted);' }, [
          el('div', {}, [`爆款 ${a.item_count} 条 · 占比 ${a.coverage}%`]),
          el('div', {}, [`均赞 ${fmtNum(a.avg_liked)} · 最高 ${fmtNum(a.max_liked)}`]),
          el('div', { style: a.opportunity === 'high' ? 'color:var(--accent);font-weight:600;' : '' }, [
            OPPORTUNITY_LABELS[a.opportunity] || a.opportunity,
          ]),
        ]),
      ]);
      card.appendChild(head);
      card.appendChild(el('p', { class: 'hint', style: 'margin:0 0 8px;font-size:12px;' }, [
        `为什么会爆：${a.mechanism || '-'}`,
      ]));

      if (linked.length) {
        const topicBlock = el('div', {
          style: 'margin:0 0 10px;padding:8px 10px;border-radius:8px;background:rgba(47,123,255,.06);border:1px solid rgba(47,123,255,.18);',
        });
        topicBlock.appendChild(el('div', { style: 'font-size:12px;font-weight:700;margin-bottom:6px;' }, ['对应上方选题']));
        linked.forEach((topic) => {
          const det = el('details', {
            id: `intelAngleTopic-${topic.index}`,
            style: 'padding:3px 0;border-radius:8px;',
          });
          det.appendChild(el('summary', {
            style: 'cursor:pointer;font-size:12.5px;font-weight:600;line-height:1.45;',
          }, [`${topic.index}. ${topic.title}`]));
          const body = el('div', { class: 'intel-topic-detail-layout' });
          const analysis = el('div', { class: 'intel-topic-analysis' });
          analysis.appendChild(buildTopicDetailContent(topic));
          body.appendChild(analysis);
          body.appendChild(buildCopyWorkbench(topic));
          det.appendChild(body);
          topicBlock.appendChild(det);
        });
        card.appendChild(topicBlock);
      }

      if ((a.suggested_keywords || []).length) {
        card.appendChild(
          el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;align-items:center;' }, [
            el('span', { class: 'hint', style: 'margin:0;font-size:12px;' }, ['建议搜索：']),
            ...(a.suggested_keywords || []).map((kw) =>
              el('button', {
                class: 'btn-secondary btn-small',
                style: 'font-size:11px;',
                onclick: () => createTopicFromMining(kw, a.name),
              }, [kw])
            ),
          ])
        );
      }

      const evidence = a.top_evidence || [];
      if (evidence.length) {
        const details = el('details', { style: 'margin-top:4px;' });
        details.appendChild(el('summary', { style: 'cursor:pointer;font-size:12.5px;color:var(--accent);' }, [
          `佐证爆款（${evidence.length}）`,
        ]));
        const ul = el('ul', { style: 'margin:8px 0 0;padding-left:18px;font-size:12.5px;line-height:1.5;' });
        evidence.forEach((ev) => {
          ul.appendChild(el('li', { style: 'margin-bottom:4px;' }, [
            el('a', { href: ev.url, target: '_blank', style: 'color:var(--accent);font-weight:600;' }, [ev.title || '(无标题)']),
            ` · 赞${fmtNum(ev.liked_count)} · ${ev.content_type || ''}`,
          ]));
        });
        details.appendChild(ul);
        card.appendChild(details);
      } else {
        card.appendChild(el('p', { class: 'hint', style: 'margin:0;font-size:12px;' }, [
          '暂无同结构爆款样本，建议按上方搜索词补采集后再生成。',
        ]));
      }
      grid.appendChild(card);
    });
    if (!grid.childNodes.length) {
      container.appendChild(el('p', { class: 'hint' }, ['先在上方生成选题，这里会按对应维度展开依据。']));
      return;
    }
    container.appendChild(grid);
  }


  async function createTopicFromMining(keyword, name) {
    const kw = (keyword || '').trim();
    if (!kw) return;
    try {
      await api('/watch-topics', {
        method: 'POST',
        body: JSON.stringify({ name: name || kw, keywords: [kw], platforms: ['xhs'] }),
      });
      alert(`已创建选题「${name || kw}」`);
      switchIntelTab('topics');
      await loadTopics();
    } catch (e) {
      alert(`创建失败：${e.message}`);
    }
  }

  const SOURCE_LABELS = { xhs_related: '相关搜索', mined: '词频挖掘' };

  function renderSuggestTable(tableEl, items) {
    if (!tableEl) return;
    tableEl.innerHTML = '';
    if (!items.length) {
      tableEl.appendChild(el('p', { class: 'hint' }, ['暂无关键词建议。']));
      return;
    }
    const table = el('table', { class: 'show' });
    table.appendChild(el('thead', {}, [el('tr', {}, [
      el('th', {}, ['关键词']), el('th', {}, ['来源']), el('th', {}, ['热度']), el('th', {}, ['操作']),
    ])]));
    const tbody = el('tbody');
    items.forEach((s) => {
      tbody.appendChild(el('tr', {}, [
        el('td', { style: 'font-weight:600;' }, [s.keyword]),
        el('td', {}, [(s.sources || []).map((k) => SOURCE_LABELS[k] || k).join('+')]),
        el('td', {}, [String(Math.round(s.score * 10) / 10)]),
        el('td', {}, [el('button', { class: 'btn-primary btn-small', onclick: () => promoteSuggestion(s) }, ['创建选题'])]),
      ]));
    });
    table.appendChild(tbody);
    tableEl.appendChild(table);
  }

  async function promoteSuggestion(s) {
    try {
      await api('/suggestions/promote', { method: 'POST', body: JSON.stringify({ keyword: s.keyword, platform: s.platform || 'xhs' }) });
      await loadTopics();
      alert(`已创建选题「${s.keyword}」`);
      switchIntelTab('topics');
    } catch (e) { alert(`失败：${e.message}`); }
  }

  async function loadBenchmark() {
    const elx = document.getElementById('intelBenchmarkTable');
    if (!elx) return;
    try {
      const data = await api('/analytics/benchmark');
      elx.innerHTML = '';
      const rows = data.topics || [];
      if (!rows.length) { elx.appendChild(el('p', { class: 'hint' }, ['暂无数据'])); return; }
      const table = el('table', { class: 'show' });
      table.appendChild(el('thead', {}, [el('tr', {}, [
        el('th', {}, ['选题']), el('th', {}, ['爆款']), el('th', {}, ['万赞']), el('th', {}, ['最高赞']),
        el('th', {}, ['主导类型']), el('th', {}, ['代表标题']),
      ])]));
      const tbody = el('tbody');
      rows.forEach((r) => {
        tbody.appendChild(el('tr', {}, [
          el('td', { style: 'font-weight:600;' }, [r.name]),
          el('td', {}, [String(r.item_count || 0)]),
          el('td', {}, [String(r.wan_like_count || 0)]),
          el('td', {}, [fmtNum(r.max_liked)]),
          el('td', {}, [r.dominant_content_type || '-']),
          el('td', { style: 'font-size:12px;max-width:180px;' }, [(r.top_title || '-').slice(0, 36)]),
        ]));
      });
      table.appendChild(tbody);
      elx.appendChild(table);
    } catch (e) {
      elx.innerHTML = '';
      elx.appendChild(el('p', { class: 'hint' }, [`加载失败：${e.message}`]));
    }
  }

  // ---------------------------------------------------------------------
  // Tab: 语料资产（上：数据追踪，下：资产库）
  // ---------------------------------------------------------------------

  function renderAssetsTab() {
    const panel = document.getElementById('intelTabAssets');
    panel.innerHTML = '';

    // --- 数据追踪（置顶） ---
    const trackSection = el('section', { class: 'panel' });
    trackSection.appendChild(el('div', { class: 'panel-head' }, ['数据追踪']));
    const trackBody = el('div', { class: 'panel-body' });
    const platformSel = el('select', { id: 'intelTrackedPlatform', style: compactInputStyle('100px') }, [
      el('option', { value: 'xhs' }, ['小红书']),
      el('option', { value: 'channels' }, ['视频号']),
    ]);
    const urlInput = el('input', {
      id: 'intelTrackedUrl',
      placeholder: '已发布链接',
      style: compactInputStyle('280px'),
    });
    const accountInput = el('input', {
      id: 'intelTrackedAccount',
      placeholder: '账号名（可选）',
      style: compactInputStyle('140px'),
    });
    trackBody.appendChild(el('div', {
      style: 'display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;',
    }, [
      platformSel,
      urlInput,
      accountInput,
      el('button', {
        id: 'intelTrackedAddBtn',
        class: 'btn-primary btn-small',
        type: 'button',
        onclick: addTrackedPost,
      }, ['回传']),
      el('button', { class: 'btn-secondary btn-small', type: 'button', onclick: refreshAllTracked }, ['全部刷新']),
    ]));
    trackBody.appendChild(el('p', {
      id: 'intelTrackedMsg',
      style: 'margin:0 0 8px;font-size:12px;color:var(--muted);',
    }, []));
    trackBody.appendChild(el('div', {
      id: 'intelTrackedOverviewWrap',
      style: 'margin:0 0 12px;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--panel-2);',
    }, [
      el('div', {
        style: 'display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;',
      }, [
        el('div', { style: 'font-size:13px;font-weight:700;' }, ['回传总览']),
        el('div', {
          id: 'intelTrackedOverviewHint',
          style: 'font-size:12px;color:var(--muted);',
        }, ['按最新快照对比各条互动']),
      ]),
      el('div', { style: 'position:relative;height:220px;' }, [
        el('canvas', { id: 'intelTrackedOverviewChart' }),
      ]),
    ]));
    trackBody.appendChild(el('div', { id: 'intelTrackedTable' }, [
      el('p', { style: 'margin:0;color:var(--muted);font-size:13px;' }, ['加载中…']),
    ]));
    trackBody.appendChild(el('div', {
      id: 'intelTrackedDetailWrap',
      style: 'margin-top:12px;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--panel-2);display:none;',
    }, [
      el('div', {
        style: 'display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;',
      }, [
        el('div', { id: 'intelTrackedDetailTitle', style: 'font-size:13px;font-weight:700;' }, ['单条趋势']),
        el('button', {
          class: 'btn-secondary btn-small',
          type: 'button',
          onclick: () => {
            selectedTrackedId = null;
            hideTrackedDetail();
            highlightTrackedRows();
          },
        }, ['收起']),
      ]),
      el('div', {
        id: 'intelTrackedDetailHint',
        style: 'font-size:12px;color:var(--muted);margin-bottom:6px;',
      }, []),
      el('div', { style: 'position:relative;height:220px;' }, [
        el('canvas', { id: 'intelTrackedDetailChart' }),
      ]),
    ]));
    trackSection.appendChild(trackBody);
    panel.appendChild(trackSection);

    // --- 资产库 ---
    const section = el('section', { class: 'panel', style: 'margin-top:14px;' });
    section.appendChild(el('div', { class: 'panel-head' }, ['资产库']));
    const body = el('div', { class: 'panel-body' });

    const searchInput = el('input', {
      id: 'intelAssetsSearch',
      placeholder: '搜索标题 / 正文 / OCR / 脚本',
      value: assetsQuery,
      style: compactInputStyle('240px'),
      onkeydown: (ev) => {
        if (ev.key === 'Enter') {
          assetsQuery = searchInput.value.trim();
          assetsOffset = 0;
          selectedAssetId = null;
          loadAssets();
        }
      },
    });

    body.appendChild(el('div', {
      style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;',
    }, [
      searchInput,
      el('button', {
        class: 'btn-primary btn-small',
        type: 'button',
        onclick: () => {
          assetsQuery = searchInput.value.trim();
          assetsOffset = 0;
          selectedAssetId = null;
          loadAssets();
        },
      }, ['搜索']),
      el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: async () => {
          try {
            await api('/corpus/sync', { method: 'POST', body: '{}' });
            loadAssets();
          } catch (e) {
            alert(`同步失败：${e.message}`);
          }
        },
      }, ['同步']),
      el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: () => {
          assetsShowAdd = !assetsShowAdd;
          renderAssetsAddForm();
        },
      }, ['新增']),
      el('select', {
        id: 'intelAssetsTopicFilter',
        style: compactInputStyle('150px'),
        onchange: (ev) => {
          assetsTopicFilter = ev.target.value;
          assetsOffset = 0;
          selectedAssetId = null;
          selectedAssetIds.clear();
          loadAssets();
        },
      }, [el('option', { value: '' }, ['全部选题'])]),
      el('button', {
        id: 'intelAssetsBulkDeleteBtn',
        class: 'btn-secondary btn-small',
        type: 'button',
        style: 'color:var(--err);',
        disabled: 'disabled',
        onclick: bulkDeleteSelectedAssets,
      }, ['删除所选']),
      el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: () => {
          selectedAssetIds.clear();
          updateAssetsSelectionUI();
          loadAssets();
        },
      }, ['清空选择']),
      el('span', { id: 'intelAssetsNote', style: 'font-size:12px;color:var(--muted);margin:0;' }, []),
      el('span', { id: 'intelAssetsSelNote', style: 'font-size:12px;color:var(--muted);margin:0;' }, []),
    ]));

    body.appendChild(el('div', { id: 'intelAssetsAddForm', style: 'margin-bottom:12px;' }));
    body.appendChild(el('div', { id: 'intelAssetsList' }, [
      el('p', { style: 'margin:0;color:var(--muted);font-size:13px;' }, ['加载中…']),
    ]));
    body.appendChild(el('div', { id: 'intelAssetsDetail', style: 'margin-top:12px;' }));
    section.appendChild(body);
    panel.appendChild(section);
    if (assetsShowAdd) renderAssetsAddForm();
  }

  function updateAssetsSelectionUI() {
    const btn = document.getElementById('intelAssetsBulkDeleteBtn');
    const note = document.getElementById('intelAssetsSelNote');
    const n = selectedAssetIds.size;
    if (btn) btn.disabled = n ? undefined : true;
    if (note) note.textContent = n ? `已选 ${n} 条` : '';
    document.querySelectorAll('[data-asset-check]').forEach((box) => {
      const id = Number(box.getAttribute('data-asset-check'));
      box.checked = selectedAssetIds.has(id);
    });
    document.querySelectorAll('[data-asset-card]').forEach((card) => {
      const id = Number(card.getAttribute('data-asset-card'));
      const on = selectedAssetIds.has(id) || selectedAssetId === id;
      card.style.borderColor = on ? 'var(--accent)' : 'var(--border)';
      card.style.background = on ? 'var(--panel-2)' : 'var(--panel)';
    });
  }

  function toggleAssetSelection(id, checked) {
    const num = Number(id);
    if (!num) return;
    if (checked) selectedAssetIds.add(num);
    else selectedAssetIds.delete(num);
    updateAssetsSelectionUI();
  }

  function setAssetIdsSelected(ids, checked) {
    (ids || []).forEach((id) => {
      const num = Number(id);
      if (!num) return;
      if (checked) selectedAssetIds.add(num);
      else selectedAssetIds.delete(num);
    });
    updateAssetsSelectionUI();
  }

  function topicOptions(selectedId, includeEmpty) {
    const opts = [];
    if (includeEmpty) opts.push(el('option', { value: '' }, ['未关联选题']));
    Object.entries(assetsTopicNames || {}).forEach(([id, name]) => {
      opts.push(el('option', {
        value: id,
        selected: selectedId === id ? 'selected' : undefined,
      }, [name]));
    });
    return opts;
  }

  function renderAssetsAddForm() {
    const box = document.getElementById('intelAssetsAddForm');
    if (!box) return;
    box.innerHTML = '';
    if (!assetsShowAdd) return;
    const urlInput = el('input', {
      id: 'intelAssetsAddUrl',
      placeholder: '粘贴小红书 / 视频号链接',
      style: compactInputStyle('320px'),
    });
    const platformSel = el('select', {
      id: 'intelAssetsAddPlatform',
      style: compactInputStyle('100px'),
    }, [
      el('option', { value: 'xhs' }, ['小红书']),
      el('option', { value: 'channels' }, ['视频号']),
    ]);
    const topicSel = el('select', {
      id: 'intelAssetsAddTopic',
      style: compactInputStyle('150px'),
    }, topicOptions(assetsTopicFilter, true));
    box.appendChild(el('div', {
      style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--panel-2);',
    }, [
      platformSel,
      urlInput,
      topicSel,
      el('button', {
        class: 'btn-primary btn-small',
        type: 'button',
        onclick: submitAddAsset,
      }, ['入库']),
      el('button', {
        class: 'btn-secondary btn-small',
        type: 'button',
        onclick: () => {
          assetsShowAdd = false;
          renderAssetsAddForm();
        },
      }, ['取消']),
    ]));
  }

  async function submitAddAsset() {
    const url = (document.getElementById('intelAssetsAddUrl') || {}).value || '';
    const platform = (document.getElementById('intelAssetsAddPlatform') || {}).value || 'xhs';
    const watch_topic_id = (document.getElementById('intelAssetsAddTopic') || {}).value || '';
    if (!url.trim()) {
      alert('请填写链接');
      return;
    }
    try {
      const data = await api('/corpus/assets', {
        method: 'POST',
        body: JSON.stringify({ url: url.trim(), platform, watch_topic_id }),
      });
      assetsShowAdd = false;
      selectedAssetId = data.item && data.item.id;
      renderAssetsAddForm();
      await loadAssets();
      if (data.item) renderAssetDetail(data.item);
    } catch (e) {
      alert(`新增失败：${e.message}`);
    }
  }

  async function ensureAssetsTopicNames() {
    if (assetsTopicNames) return;
    assetsTopicNames = {};
    try {
      const data = await api('/watch-topics');
      const sel = document.getElementById('intelAssetsTopicFilter');
      (data.items || []).forEach((t) => {
        assetsTopicNames[t.id] = t.name;
        if (sel) {
          sel.appendChild(el('option', {
            value: t.id,
            selected: assetsTopicFilter === t.id ? 'selected' : undefined,
          }, [t.name]));
        }
      });
    } catch (e) { /* ignore */ }
  }

  function assetTopicName(item) {
    if (item.topic_name) return item.topic_name;
    if (!item.watch_topic_id) return '未关联选题';
    return (assetsTopicNames && assetsTopicNames[item.watch_topic_id]) || '其他选题';
  }

  function platformLabel(platform) {
    if (platform === 'channels') return '视频号';
    if (platform === 'xhs') return '小红书';
    return platform || '未知';
  }

  function renderAssetCard(item) {
    const tags = [];
    if (item.note_type) tags.push(item.note_type);
    if (item.has_script) tags.push('脚本');
    if (item.has_ocr) tags.push('OCR');
    const checked = selectedAssetIds.has(item.id);
    const active = checked || selectedAssetId === item.id;
    const checkbox = el('input', {
      type: 'checkbox',
      'data-asset-check': String(item.id),
      checked: checked ? 'checked' : undefined,
      onclick: (ev) => {
        ev.stopPropagation();
        toggleAssetSelection(item.id, ev.target.checked);
      },
      onchange: (ev) => {
        ev.stopPropagation();
        toggleAssetSelection(item.id, ev.target.checked);
      },
    });
    return el('div', {
      'data-asset-card': String(item.id),
      style: [
        'display:flex;flex-direction:column;align-items:stretch;text-align:left;',
        'padding:10px 12px;border-radius:10px;gap:6px;cursor:pointer;',
        `border:1px solid ${active ? 'var(--accent)' : 'var(--border)'};`,
        `background:${active ? 'var(--panel-2)' : 'var(--panel)'};`,
      ].join(''),
      onclick: () => {
        selectedAssetId = item.id;
        updateAssetsSelectionUI();
        renderAssetDetail(item);
      },
    }, [
      el('div', {
        style: 'display:flex;align-items:flex-start;gap:8px;',
      }, [
        el('label', {
          style: 'display:flex;padding-top:2px;cursor:pointer;',
          onclick: (ev) => ev.stopPropagation(),
        }, [checkbox]),
        el('div', {
          style: 'flex:1;min-width:0;font-size:13px;font-weight:700;line-height:1.4;color:var(--text);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;',
        }, [item.title || '(无标题)']),
      ]),
      el('div', {
        style: 'display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted);padding-left:22px;',
      }, [
        el('span', { style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' }, [
          item.author || platformLabel(item.platform),
        ]),
        el('span', { style: 'flex-shrink:0;font-weight:600;color:var(--text);' }, [`赞 ${fmtNum(item.liked_count || 0)}`]),
      ]),
      tags.length
        ? el('div', { style: 'display:flex;gap:4px;flex-wrap:wrap;padding-left:22px;' }, tags.map((t) => el('span', {
          class: 'badge',
          style: 'font-size:10.5px;padding:2px 6px;',
        }, [t])))
        : null,
    ]);
  }

  function renderAssetDetail(item) {
    const box = document.getElementById('intelAssetsDetail');
    if (!box || !item) return;
    box.innerHTML = '';
    const preview = cleanCorpusPreview(item.desc_preview || '');
    const kids = [
      el('div', {
        style: 'display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:8px;',
      }, [
        el('div', { style: 'flex:1;min-width:0;' }, [
          item.url
            ? el('a', {
              href: item.url,
              target: '_blank',
              rel: 'noopener',
              style: 'font-size:14px;font-weight:700;line-height:1.45;color:var(--accent);text-decoration:none;',
            }, [item.title || '(无标题)'])
            : el('div', { style: 'font-size:14px;font-weight:700;line-height:1.45;' }, [item.title || '(无标题)']),
          el('div', {
            style: 'margin-top:4px;font-size:12px;color:var(--muted);',
          }, [
            `${platformLabel(item.platform)} · ${item.author || '未知作者'} · 赞 ${fmtNum(item.liked_count || 0)}`,
            item.note_type ? ` · ${item.note_type}` : '',
            item.synced_date ? ` · ${item.synced_date}` : '',
            ` · ${assetTopicName(item)}`,
          ]),
        ]),
        el('button', {
          class: 'btn-secondary btn-small',
          type: 'button',
          onclick: () => {
            selectedAssetId = null;
            box.innerHTML = '';
            updateAssetsSelectionUI();
          },
        }, ['收起']),
      ]),
    ];
    if (preview) {
      kids.push(makeFold('正文预览', el('div', {
        style: 'font-size:12.5px;line-height:1.55;color:var(--muted);',
      }, [preview]), { defaultOpen: true, compact: true }));
    }
    if (item.script_preview) {
      kids.push(makeFold('视频脚本', el('div', {
        style: 'font-size:12.5px;line-height:1.55;color:var(--muted);white-space:pre-wrap;',
      }, [item.script_preview]), { defaultOpen: false, compact: true }));
    }
    if (item.ocr_preview) {
      kids.push(makeFold('图片 OCR', el('div', {
        style: 'font-size:12.5px;line-height:1.55;color:var(--muted);white-space:pre-wrap;',
      }, [item.ocr_preview]), { defaultOpen: false, compact: true }));
    }
    box.appendChild(el('div', {
      style: 'padding:12px 14px;border:1px solid var(--border);border-radius:12px;background:var(--panel-2);',
    }, kids));
  }

  async function bulkDeleteSelectedAssets() {
    const ids = Array.from(selectedAssetIds);
    if (!ids.length) return;
    if (!confirm(`确定删除已选的 ${ids.length} 条语料？`)) return;
    try {
      const result = await api('/corpus/assets/bulk-delete', {
        method: 'POST',
        body: JSON.stringify({ ids }),
      });
      selectedAssetIds.clear();
      if (selectedAssetId && ids.includes(selectedAssetId)) {
        selectedAssetId = null;
        const detail = document.getElementById('intelAssetsDetail');
        if (detail) detail.innerHTML = '';
      }
      await loadAssets();
      const deleted = (result && result.deleted) || ids.length;
      const note = document.getElementById('intelAssetsNote');
      if (note) note.textContent = `已删除 ${deleted} 条`;
    } catch (e) {
      alert(`删除失败：${e.message}`);
    }
  }

  function renderAssetGrid(items) {
    return el('div', {
      style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;',
    }, items.map(renderAssetCard));
  }

  function renderBatchSelectBar(label, ids) {
    const allSelected = ids.length > 0 && ids.every((id) => selectedAssetIds.has(id));
    return el('div', {
      style: 'display:flex;align-items:center;gap:8px;margin:0 0 6px;',
    }, [
      el('label', {
        style: 'display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);cursor:pointer;user-select:none;',
      }, [
        el('input', {
          type: 'checkbox',
          checked: allSelected ? 'checked' : undefined,
          onchange: (ev) => setAssetIdsSelected(ids, ev.target.checked),
        }),
        `选中本批（${ids.length}）`,
      ]),
      el('span', { style: 'font-size:12px;color:var(--muted);' }, [label || '']),
    ]);
  }

  function renderTopicDateGroups(groups) {
    const wrap = el('div', { style: 'display:flex;flex-direction:column;gap:8px;' });
    groups.forEach((topicGroup) => {
      const topicIds = [];
      (topicGroup.dates || []).forEach((dateGroup) => {
        (dateGroup.items || []).forEach((item) => topicIds.push(item.id));
      });
      const dateFolds = (topicGroup.dates || []).map((dateGroup) => {
        const dateIds = (dateGroup.items || []).map((item) => item.id);
        return makeFold(
          `${dateGroup.date || '未知日期'} · ${dateGroup.count} 条`,
          el('div', { style: 'display:flex;flex-direction:column;gap:8px;' }, [
            renderBatchSelectBar('按日期', dateIds),
            renderAssetGrid(dateGroup.items || []),
          ]),
          { defaultOpen: false, compact: true }
        );
      });
      wrap.appendChild(makeFold(
        `${topicGroup.topic_name || '未关联选题'} · ${topicGroup.count} 条`,
        el('div', { style: 'display:flex;flex-direction:column;gap:6px;padding-top:4px;' }, [
          renderBatchSelectBar('按选题整批', topicIds),
          ...dateFolds,
        ]),
        { defaultOpen: false, compact: false }
      ));
    });
    return wrap;
  }

  async function loadAssets() {
    const list = document.getElementById('intelAssetsList');
    const note = document.getElementById('intelAssetsNote');
    if (!list) return;
    if (note) note.textContent = '加载中…';
    try {
      await ensureAssetsTopicNames();
      const query = new URLSearchParams({
        limit: '200',
        offset: '0',
        group_by: assetsGroupBy || 'topic_date',
      });
      if (assetsQuery) query.set('q', assetsQuery);
      if (assetsTopicFilter) query.set('topic_id', assetsTopicFilter);
      const data = await api(`/corpus/assets?${query.toString()}`);
      const items = data.items || [];
      const groups = data.groups || [];
      const total = data.total || 0;
      const summary = data.summary || {};
      latestAssetItems = items;
      const valid = new Set(items.map((item) => item.id));
      selectedAssetIds = new Set(Array.from(selectedAssetIds).filter((id) => valid.has(id)));
      if (note) {
        const parts = [`${summary.total || total} 条`];
        if (summary.with_script) parts.push(`脚本 ${summary.with_script}`);
        if (summary.with_ocr) parts.push(`OCR ${summary.with_ocr}`);
        if (assetsQuery) parts.unshift(`命中 ${total}`);
        note.textContent = parts.join(' · ');
      }

      const sel = document.getElementById('intelAssetsTopicFilter');
      if (sel && (data.topics || []).length && sel.options.length <= 1) {
        (data.topics || []).forEach((t) => {
          assetsTopicNames = assetsTopicNames || {};
          assetsTopicNames[t.id] = t.name;
          sel.appendChild(el('option', {
            value: t.id,
            selected: assetsTopicFilter === t.id ? 'selected' : undefined,
          }, [t.name]));
        });
      }

      list.innerHTML = '';
      if (!items.length) {
        list.appendChild(el('p', {
          style: 'margin:0;color:var(--muted);font-size:13px;',
        }, [assetsQuery ? '没有匹配语料' : '暂无语料']));
        updateAssetsSelectionUI();
        return;
      }

      if (groups.length) {
        list.appendChild(renderTopicDateGroups(groups));
      } else {
        list.appendChild(el('div', { style: 'display:flex;flex-direction:column;gap:8px;' }, [
          renderBatchSelectBar('当前列表', items.map((item) => item.id)),
          renderAssetGrid(items),
        ]));
      }

      const selected = items.find((item) => item.id === selectedAssetId);
      if (selected) renderAssetDetail(selected);
      else {
        const detail = document.getElementById('intelAssetsDetail');
        if (detail) detail.innerHTML = '';
      }
      updateAssetsSelectionUI();
    } catch (e) {
      list.innerHTML = '';
      if (note) note.textContent = '';
      list.appendChild(el('p', {
        style: 'margin:0;color:var(--err);font-size:13px;',
      }, [`加载失败：${e.message}`]));
    }
  }

  // --- 数据追踪 ---
  function trackedMetric(post) {
    const m = post.metrics || {};
    return {
      liked: Number(m.liked_count || m.liked || post.latest_liked || 0),
      collected: Number(m.collected_count || m.collected || post.latest_collected || 0),
      comment: Number(m.comment_count || m.comment || post.latest_comment || 0),
      share: Number(m.share_count || m.share || post.latest_share || 0),
    };
  }

  function trackedLabel(post) {
    const raw = (post.title || post.account_name || post.url || `内容${post.id}`).trim();
    return raw.length > 14 ? `${raw.slice(0, 14)}…` : raw;
  }

  function destroyTrackedCharts() {
    if (trackedOverviewChart) {
      trackedOverviewChart.destroy();
      trackedOverviewChart = null;
    }
    if (trackedDetailChart) {
      trackedDetailChart.destroy();
      trackedDetailChart = null;
    }
  }

  function hideTrackedDetail() {
    const wrap = document.getElementById('intelTrackedDetailWrap');
    if (wrap) wrap.style.display = 'none';
    if (trackedDetailChart) {
      trackedDetailChart.destroy();
      trackedDetailChart = null;
    }
  }

  function highlightTrackedRows() {
    document.querySelectorAll('[data-tracked-row]').forEach((tr) => {
      const id = Number(tr.getAttribute('data-tracked-row'));
      tr.style.background = selectedTrackedId === id ? 'var(--panel-2)' : '';
    });
  }

  async function renderTrackedOverview(items) {
    const canvas = document.getElementById('intelTrackedOverviewChart');
    const hint = document.getElementById('intelTrackedOverviewHint');
    const wrap = document.getElementById('intelTrackedOverviewWrap');
    if (!canvas) return;
    await ensureChartJs();
    if (trackedOverviewChart) {
      trackedOverviewChart.destroy();
      trackedOverviewChart = null;
    }
    if (!items.length) {
      if (wrap) wrap.style.display = 'none';
      return;
    }
    if (wrap) wrap.style.display = '';

    const palette = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4', '#84cc16', '#f97316'];
    const top = items.slice(0, 8);
    const histories = await Promise.all(top.map(async (post) => {
      try {
        const data = await api(`/tracked/${post.id}/history`);
        return { post, snapshots: data.items || [] };
      } catch (e) {
        return { post, snapshots: [] };
      }
    }));
    const withHistory = histories.filter(({ snapshots }) => snapshots.length);
    if (!withHistory.length) {
      if (hint) hint.textContent = '暂无历史快照，点「全部刷新」后查看时间趋势';
      return;
    }

    const timeSet = new Set();
    withHistory.forEach(({ snapshots }) => {
      snapshots.forEach((s) => {
        if (s.captured_at) timeSet.add(s.captured_at);
      });
    });
    const timeKeys = Array.from(timeSet).sort();
    const labels = timeKeys.map((t) => t.slice(5, 16));

    let datasets = [];
    const activePosts = withHistory.filter(({ post }) => !post.last_error);
    if (activePosts.length === 1) {
      const snapshots = activePosts[0].snapshots;
      const snapLabels = snapshots.map((s) => (s.captured_at || '').slice(5, 16));
      datasets = [
        { label: '赞', data: snapshots.map((s) => s.liked_count || 0), borderColor: '#3b82f6', tension: 0.25, pointRadius: 3 },
        { label: '藏', data: snapshots.map((s) => s.collected_count || 0), borderColor: '#10b981', tension: 0.25, pointRadius: 3 },
        { label: '评', data: snapshots.map((s) => s.comment_count || 0), borderColor: '#f59e0b', tension: 0.25, pointRadius: 3 },
        { label: '转', data: snapshots.map((s) => s.share_count || 0), borderColor: '#8b5cf6', tension: 0.25, pointRadius: 3 },
      ];
      if (hint) hint.textContent = `${snapLabels.length} 个时间点 · 点击表格行看单条详情`;
      trackedOverviewChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels: snapLabels, datasets },
        options: trackedLineChartOptions({ onClickPost: activePosts[0].post }),
      });
      return;
    }

    datasets = activePosts.map(({ post, snapshots }, idx) => {
      const byTime = new Map(snapshots.map((s) => [s.captured_at, s]));
      let lastVal = null;
      const data = timeKeys.map((t) => {
        const snap = byTime.get(t);
        if (snap) lastVal = Number(snap.liked_count || 0);
        return lastVal;
      });
      const color = palette[idx % palette.length];
      return {
        label: trackedLabel(post),
        data,
        borderColor: color,
        backgroundColor: `${color}22`,
        tension: 0.25,
        pointRadius: 2,
        spanGaps: true,
      };
    });

    if (hint) {
      hint.textContent = items.length > 8
        ? `时间轴 · 展示 ${activePosts.length} / ${items.length} 条（赞）`
        : `时间轴 · 共 ${activePosts.length} 条（赞）`;
    }

    trackedOverviewChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels, datasets },
      options: trackedLineChartOptions({
        onClickPost: (idx) => {
          const target = activePosts[idx];
          if (target) showTrackedHistory(target.post);
        },
        clickByDatasetIndex: true,
      }),
    });
  }

  function trackedLineChartOptions(opts) {
    const options = opts || {};
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: {
          title: { display: true, text: '时间', font: { size: 11 } },
          ticks: { maxRotation: 35, minRotation: 0, font: { size: 10 } },
        },
        y: { beginAtZero: true, title: { display: true, text: '互动量', font: { size: 11 } } },
      },
      onClick: (evt, elements) => {
        if (!elements.length || !options.onClickPost) return;
        const el = elements[0];
        if (options.clickByDatasetIndex) {
          options.onClickPost(el.datasetIndex);
        } else {
          options.onClickPost();
        }
      },
    };
  }

  async function loadTracked() {
    const tableEl = document.getElementById('intelTrackedTable');
    if (!tableEl) return;
    try {
      const data = await api('/tracked');
      const items = data.items || [];
      latestTrackedItems = items;
      tableEl.innerHTML = '';
      if (!items.length) {
        destroyTrackedCharts();
        hideTrackedDetail();
        const wrap = document.getElementById('intelTrackedOverviewWrap');
        if (wrap) wrap.style.display = 'none';
        tableEl.appendChild(el('p', {
          style: 'margin:0;color:var(--muted);font-size:13px;',
        }, ['暂无追踪内容，粘贴已发布链接后点「回传」']));
        return;
      }
      await renderTrackedOverview(items);

      const table = el('table', { class: 'show', style: 'width:100%;border-collapse:collapse;font-size:12.5px;' });
      table.appendChild(el('thead', {}, [
        el('tr', {}, ['账号', '标题', '赞', '藏', '评', '转', '刷新', ''].map((h) => el('th', {
          style: 'text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);color:var(--muted);font-weight:600;',
        }, [h]))),
      ]));
      const tbody = el('tbody');
      items.forEach((post) => {
        const m = trackedMetric(post);
        const tr = el('tr', {
          'data-tracked-row': String(post.id),
          style: `cursor:pointer;${selectedTrackedId === post.id ? 'background:var(--panel-2);' : ''}`,
          title: '点击查看该条互动趋势',
          onclick: () => showTrackedHistory(post),
        }, [
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);' }, [post.account_name || '-']),
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);max-width:240px;' }, [
            (post.title || post.url || '-').slice(0, 42),
          ]),
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);' }, [fmtNum(m.liked)]),
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);' }, [fmtNum(m.collected)]),
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);' }, [fmtNum(m.comment)]),
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);' }, [fmtNum(m.share)]),
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);color:var(--muted);font-size:11.5px;' }, [
            post.last_refreshed_at || '-',
          ]),
          el('td', { style: 'padding:7px 8px;border-bottom:1px solid var(--border);white-space:nowrap;' }, [
            el('button', {
              class: 'btn-secondary btn-small',
              type: 'button',
              style: 'padding:2px 8px;font-size:11px;margin-right:4px;',
              onclick: (ev) => { ev.stopPropagation(); refreshTracked(post.id); },
            }, ['刷新']),
            el('button', {
              class: 'btn-secondary btn-small',
              type: 'button',
              style: 'padding:2px 8px;font-size:11px;color:var(--err);',
              onclick: (ev) => { ev.stopPropagation(); deleteTracked(post.id); },
            }, ['删']),
          ]),
        ]);
        tbody.appendChild(tr);
        if (post.last_error) {
          tbody.appendChild(el('tr', {}, [
            el('td', {
              colspan: '8',
              style: 'padding:0 8px 8px;color:var(--err);font-size:11.5px;border-bottom:1px solid var(--border);',
            }, [String(post.last_error).slice(0, 180)]),
          ]));
        }
      });
      table.appendChild(tbody);
      tableEl.appendChild(table);

      if (selectedTrackedId) {
        const selected = items.find((p) => p.id === selectedTrackedId);
        if (selected) await showTrackedHistory(selected, { keepSelection: true });
        else hideTrackedDetail();
      }
    } catch (e) {
      tableEl.innerHTML = '';
      tableEl.appendChild(el('p', {
        style: 'margin:0;color:var(--err);font-size:13px;',
      }, [`加载失败：${e.message}`]));
    }
  }

  async function showTrackedHistory(post, opts) {
    if (!post || !post.id) return;
    selectedTrackedId = post.id;
    if (!(opts && opts.keepSelection)) highlightTrackedRows();

    const wrap = document.getElementById('intelTrackedDetailWrap');
    const titleEl = document.getElementById('intelTrackedDetailTitle');
    const hintEl = document.getElementById('intelTrackedDetailHint');
    const canvas = document.getElementById('intelTrackedDetailChart');
    if (!canvas) return;
    if (wrap) {
      wrap.style.display = '';
      wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    if (titleEl) titleEl.textContent = (post.title || '单条趋势').slice(0, 40);
    if (hintEl) {
      hintEl.style.color = 'var(--muted)';
      hintEl.textContent = '加载趋势中…';
    }

    try {
      await ensureChartJs();
      const data = await api(`/tracked/${post.id}/history`);
      const items = data.items || [];
      if (trackedDetailChart) {
        trackedDetailChart.destroy();
        trackedDetailChart = null;
      }
      if (!items.length) {
        if (hintEl) {
          hintEl.style.color = 'var(--muted)';
          hintEl.textContent = '暂无历史快照。点「刷新」后再看趋势。';
        }
        return;
      }
      if (hintEl) {
        hintEl.style.color = 'var(--muted)';
        hintEl.textContent = `${items.length} 个快照 · ${post.account_name || platformLabel(post.platform) || ''}`;
      }
      const labels = items.map((s) => (s.captured_at || '').slice(5, 16));
      trackedDetailChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels,
          datasets: [
            { label: '赞', data: items.map((s) => s.liked_count || 0), borderColor: '#3b82f6', tension: 0.25, pointRadius: 3 },
            { label: '藏', data: items.map((s) => s.collected_count || 0), borderColor: '#10b981', tension: 0.25, pointRadius: 3 },
            { label: '评', data: items.map((s) => s.comment_count || 0), borderColor: '#f59e0b', tension: 0.25, pointRadius: 3 },
            { label: '转', data: items.map((s) => s.share_count || 0), borderColor: '#8b5cf6', tension: 0.25, pointRadius: 3 },
          ],
        },
        options: trackedLineChartOptions(),
      });
    } catch (e) {
      if (hintEl) {
        hintEl.style.color = 'var(--err)';
        hintEl.textContent = `趋势加载失败：${e.message}`;
      }
    }
  }

  async function addTrackedPost() {
    const platform = (document.getElementById('intelTrackedPlatform') || {}).value || 'xhs';
    const url = ((document.getElementById('intelTrackedUrl') || {}).value || '').trim();
    const account_name = ((document.getElementById('intelTrackedAccount') || {}).value || '').trim();
    const msg = document.getElementById('intelTrackedMsg');
    const btn = document.getElementById('intelTrackedAddBtn');
    if (!url) {
      alert('请填写链接');
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = '回传中…';
    }
    if (msg) {
      msg.style.color = 'var(--muted)';
      msg.textContent = '正在抓取互动数据…';
    }
    try {
      const post = await api('/tracked', {
        method: 'POST',
        body: JSON.stringify({ platform, url, account_name }),
      });
      const urlEl = document.getElementById('intelTrackedUrl');
      if (urlEl) urlEl.value = '';
      if (post && post.id) selectedTrackedId = post.id;
      await loadTracked();
      if (post && post.last_error) {
        if (msg) {
          msg.style.color = 'var(--err)';
          msg.textContent = `已登记，但抓取失败：${post.last_error}`;
        }
        alert(`已添加，但抓取指标失败：${post.last_error}`);
      } else if (msg) {
        msg.style.color = 'var(--ok)';
        msg.textContent = `已回传：${(post && post.title) || url}`;
      }
      if (post && !post.last_error) await showTrackedHistory(post);
    } catch (e) {
      if (msg) {
        msg.style.color = 'var(--err)';
        msg.textContent = `回传失败：${e.message}`;
      }
      alert(`添加失败：${e.message}`);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '回传';
      }
    }
  }

  async function refreshTracked(postId) {
    try {
      const post = await api(`/tracked/${postId}/refresh`, { method: 'POST' });
      selectedTrackedId = postId;
      await loadTracked();
      if (post) await showTrackedHistory(post);
    } catch (e) {
      alert(`刷新失败：${e.message}`);
    }
  }

  async function refreshAllTracked() {
    const msg = document.getElementById('intelTrackedMsg');
    if (msg) {
      msg.style.color = 'var(--muted)';
      msg.textContent = '正在全部刷新…';
    }
    try {
      await api('/tracked/refresh-all', { method: 'POST' });
      await loadTracked();
      if (msg) {
        msg.style.color = 'var(--ok)';
        msg.textContent = '全部刷新完成';
      }
    } catch (e) {
      if (msg) {
        msg.style.color = 'var(--err)';
        msg.textContent = `刷新失败：${e.message}`;
      }
      alert(`刷新失败：${e.message}`);
    }
  }

  async function deleteTracked(postId) {
    if (!confirm('确定删除该追踪？')) return;
    try {
      await api(`/tracked/${postId}`, { method: 'DELETE' });
      if (selectedTrackedId === postId) {
        selectedTrackedId = null;
        hideTrackedDetail();
      }
      await loadTracked();
    } catch (e) {
      alert(`删除失败：${e.message}`);
    }
  }

  function init() {
    if (inited && document.getElementById('intelTabTopics')) {
      if (currentIntelTab === 'topics') loadTopics();
      if (currentIntelTab === 'mining') { loadCorpusAnalysis(); loadMiningInsights(); loadBenchmark(); }
      if (currentIntelTab === 'assets') { loadTracked(); loadAssets(); }
      return;
    }
    inited = true;
    renderShell();
  }

  window.IntelApp = { init };
})();
