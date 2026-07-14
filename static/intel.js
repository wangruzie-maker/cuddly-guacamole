/* 内容情报 — 分 Tab：选题建立 / 选题挖掘 / 数据追踪 */
(function () {
  const API = '/api/intel';
  const PAGE_SIZE = 10;
  let inited = false;
  let topics = [];
  const topicPages = {};
  let currentIntelTab = 'topics';
  let trackedChart = null;
  let selectedTrackedId = null;

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'style') node.style.cssText = v;
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null) node.setAttribute(k, v);
    });
    (children || []).forEach((c) => {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
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

  function sendToXhsExtract(url) {
    if (window.AppBridge && typeof window.AppBridge.openXhsExtract === 'function') {
      window.AppBridge.openXhsExtract(url);
      return;
    }
    window.open(url, '_blank');
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
    root.appendChild(el('div', { id: 'intelTabTracked', class: 'intel-tab-panel', hidden: 'hidden' }));
    renderTopicsTab();
    renderMiningTab();
    renderTrackedTab();
    switchIntelTab('topics');
    refreshLoginStatus();
    maybeShowOnboarding();
  }

  function renderIntelSubTabs() {
    const bar = el('nav', {
      class: 'intel-subtabs',
      style: 'display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;',
    });
    [
      ['topics', '选题建立'],
      ['mining', '选题挖掘'],
      ['tracked', '数据追踪'],
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
    document.getElementById('intelTabTracked').hidden = tab !== 'tracked';
    if (tab === 'mining') {
      loadMiningInsights();
      loadBenchmark();
    }
    if (tab === 'tracked') loadTracked();
  }

  function renderStatusBar() {
    return el('div', {
      style: 'display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:14px;padding:10px 14px;border-radius:12px;background:var(--panel-2);border:1px solid var(--border);',
    }, [
      el('span', { id: 'intelXhsStatus', class: 'hint', style: 'margin:0;' }, ['小红书：检测中…']),
      el('button', { class: 'btn-secondary btn-small', id: 'intelXhsLoginBtn', onclick: triggerXhsLogin }, ['登录小红书']),
      el('span', { class: 'hint', style: 'margin:0;flex:1 1 200px;' }, [
        '选题爆款默认折叠；切换上方 Tab 使用不同功能，无需长页面向下翻。',
      ]),
    ]);
  }

  async function refreshLoginStatus() {
    const statusEl = document.getElementById('intelXhsStatus');
    if (!statusEl) return;
    try {
      const resp = await fetch('/api/xhs/login-status');
      const data = await resp.json();
      if (data.logged_in) {
        statusEl.textContent = '小红书：✅ 已登录';
        statusEl.style.color = 'var(--ok)';
      } else {
        statusEl.textContent = '小红书：未登录';
        statusEl.style.color = 'var(--err)';
      }
    } catch (e) {
      statusEl.textContent = '小红书：状态未知';
      statusEl.style.color = 'var(--muted)';
    }
  }

  async function triggerXhsLogin(ev) {
    const btn = ev && ev.currentTarget ? ev.currentTarget : document.getElementById('intelXhsLoginBtn');
    if (!btn) return;
    const old = btn.textContent;
    btn.disabled = true;
    btn.textContent = '唤起中…';
    try {
      const statusResp = await fetch('/api/xhs/login-status');
      const status = await statusResp.json().catch(() => ({}));
      if (status.logged_in) {
        await refreshLoginStatus();
        return;
      }
      const loginResp = await fetch('/api/xhs/login', { method: 'POST' });
      const r = await loginResp.json().catch(() => ({}));
      if (!loginResp.ok) throw new Error(r.detail || `触发失败 (${loginResp.status})`);
      alert(r.message || '请在弹出的 Chrome 窗口完成登录');
      setTimeout(refreshLoginStatus, 2000);
    } catch (e) {
      alert(`登录失败：${e.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  function maybeShowOnboarding() {
    if (localStorage.getItem('intel_onboarded_v112')) return;
    const overlay = el('div', {
      style: 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;',
    });
    const card = el('div', {
      style: 'max-width:420px;width:100%;background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:20px;',
    });
    card.appendChild(el('h3', { style: 'margin:0 0 12px;font-size:18px;' }, ['内容情报怎么用']));
    [
      '① 选题建立：创建选题 → 运行 → 展开卡片查看爆款',
      '② 选题挖掘：看建议词、跨选题对标',
      '③ 数据追踪：登记已发布链接，查看表现曲线',
    ].forEach((text) => card.appendChild(el('p', { class: 'hint', style: 'margin:0 0 8px;line-height:1.5;' }, [text])));
    card.appendChild(
      el('button', {
        class: 'btn-primary',
        style: 'margin-top:8px;width:100%;',
        onclick: () => {
          localStorage.setItem('intel_onboarded_v112', '1');
          overlay.remove();
        },
      }, ['知道了'])
    );
    overlay.appendChild(card);
    document.body.appendChild(overlay);
  }

  // ---------------------------------------------------------------------
  // Tab: 选题建立
  // ---------------------------------------------------------------------

  function renderTopicsTab() {
    const panel = document.getElementById('intelTabTopics');
    panel.innerHTML = '';
    const section = el('section', { class: 'panel' });
    section.appendChild(el('div', { class: 'panel-head' }, ['创建选题']));
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
        el('button', { class: 'btn-primary', onclick: createTopic }, ['创建选题']),
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

    const advanced = el('details', { style: 'margin-bottom:10px;' }, [
      el('summary', { class: 'hint', style: 'cursor:pointer;' }, ['高级选项']),
    ]);
    const advBody = el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding-top:8px;' });
    const limitInput = el('input', { id: 'intelTopicLimit', type: 'number', value: '20', min: '1', max: '50', style: inputStyle('70px') });
    const intervalInput = el('input', { id: 'intelTopicInterval', type: 'number', value: '360', min: '15', style: inputStyle('70px') });
    const SORT_ROUND_OPTIONS = ['综合', '最新', '最多点赞', '最多评论', '最多收藏'];
    SORT_ROUND_OPTIONS.forEach((label, idx) => {
      advBody.appendChild(
        el('label', { class: 'checkbox-row', style: 'margin:0;font-size:12px;' }, [
          el('input', { type: 'checkbox', class: 'intelTopicSortRound', value: label, checked: idx === 0 ? 'checked' : undefined }),
          ` ${label}`,
        ])
      );
    });
    const noteTypeSelect = el('select', { id: 'intelTopicNoteType', style: inputStyle('100px') }, [
      el('option', { value: '' }, ['类型不限']),
      el('option', { value: '视频' }, ['视频']),
      el('option', { value: '图文' }, ['图文']),
    ]);
    advBody.appendChild(el('label', { class: 'checkbox-row', style: 'margin:0' }, ['每轮', limitInput, '条']));
    advBody.appendChild(el('label', { class: 'checkbox-row', style: 'margin:0' }, ['间隔', intervalInput, '分']));
    advBody.appendChild(noteTypeSelect);
    ['intelTopicMinLiked', 'intelTopicMinCollected', 'intelTopicMinComments'].forEach((id, i) => {
      const labels = ['最低赞', '最低藏', '最低评'];
      advBody.appendChild(
        el('label', { class: 'checkbox-row', style: 'margin:0' }, [
          labels[i],
          el('input', { id, type: 'number', value: '0', min: '0', style: inputStyle('60px') }),
        ])
      );
    });
    advanced.appendChild(advBody);
    body.appendChild(advanced);
    body.appendChild(el('p', { id: 'intelTopicCreateMsg', class: 'hint', style: 'margin:0 0 12px' }, []));

    section.appendChild(body);
    panel.appendChild(section);

    const listSection = el('section', { class: 'panel', style: 'margin-top:14px' });
    listSection.appendChild(el('div', { class: 'panel-head' }, ['我的选题']));
    listSection.appendChild(el('div', { class: 'panel-body', id: 'intelTopicList' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    panel.appendChild(listSection);
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

    const block = el('div', {
      style: 'margin-bottom:12px;border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--panel);',
    });

    const head = el('div', { style: 'padding:12px 14px;background:var(--panel-2);' });
    head.appendChild(
      el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;' }, [
        el('div', { style: 'flex:1 1 200px;' }, [
          el('div', { style: 'font-size:16px;font-weight:700;margin-bottom:4px;' }, [t.name]),
          el('div', { class: 'hint', style: 'font-size:12.5px;' }, [
            `${platformsLabel} · ${kwLabel} · ${t.enabled ? '启用' : '停用'} · 已收录 ${count} 条`,
          ]),
          el('div', {
            class: 'hint',
            style: `font-size:12px;margin-top:4px;${isRunMessageWarning(t.last_run_message) ? 'color:var(--err);' : ''}`,
          }, [`最近运行：${runMsg}`]),
        ]),
        el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;' }, [
          el('button', { class: 'btn-primary btn-small', onclick: (ev) => runTopicNow(t.id, ev.currentTarget) }, ['运行一次']),
          el('button', { class: 'btn-secondary btn-small', onclick: () => exportTopicPack(t.id, t.name) }, ['导出选题包']),
          el('button', { class: 'btn-secondary btn-small', onclick: () => toggleDirections(t.id) }, ['选题方向']),
          el('button', { class: 'btn-secondary btn-small', onclick: () => toggleTopic(t) }, [t.enabled ? '停用' : '启用']),
          el('button', { class: 'btn-danger btn-small', onclick: () => deleteTopic(t.id) }, ['删除']),
        ]),
      ])
    );
    block.appendChild(head);

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
      const data = await api(`/watch-topics/${topicId}/items?page=${page}&page_size=${PAGE_SIZE}`);
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
    if (!items.length) {
      container.appendChild(el('p', { class: 'hint' }, ['该选题暂无爆款。']));
      return;
    }
    const table = el('table', { class: 'show', style: 'width:100%;' });
    table.appendChild(
      el('thead', {}, [
        el('tr', {}, [
          el('th', { style: 'width:36px;' }, ['#']),
          el('th', { style: 'width:56px;' }, ['封面']),
          el('th', {}, ['标题 / 作者']),
          el('th', { style: 'width:72px;' }, ['内容类型']),
          el('th', { style: 'min-width:260px;' }, ['转 · 赞 · 评 · 播 · 搜 · 藏']),
          el('th', { style: 'width:88px;' }, ['操作']),
        ]),
      ])
    );
    const tbody = el('tbody');
    const baseIdx = (data.page - 1) * data.page_size;
    items.forEach((item, idx) => {
      const coverCell = item.cover_url
        ? el('img', { src: item.cover_url, style: 'width:44px;height:44px;object-fit:cover;border-radius:6px;' })
        : el('div', { style: 'width:44px;height:44px;border-radius:6px;background:var(--panel-2);font-size:10px;display:flex;align-items:center;justify-content:center;color:var(--muted);' }, ['图文']);
      tbody.appendChild(
        el('tr', {}, [
          el('td', {}, [String(baseIdx + idx + 1)]),
          el('td', {}, [coverCell]),
          el('td', {}, [
            el('div', { style: 'font-size:13px;max-width:300px;' }, [item.title || '(无标题)']),
            el('div', { class: 'hint', style: 'font-size:11.5px;' }, [item.author || '-']),
          ]),
          el('td', { style: 'font-size:11.5px;' }, [item.content_type || '其他']),
          el('td', {}, [renderMetrics(item)]),
          el('td', { style: 'display:flex;gap:4px;' }, [
            el('a', { href: item.url, target: '_blank', style: 'color:var(--accent);font-size:12px;' }, ['打开']),
            item.platform === 'xhs'
              ? el('button', { class: 'btn-secondary btn-small', style: 'font-size:11px;padding:2px 6px;', onclick: () => sendToXhsExtract(item.url) }, ['提取'])
              : null,
          ]),
        ])
      );
    });
    table.appendChild(tbody);
    container.appendChild(table);
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
      const result = await api(`/watch-topics/${topicId}/run`, { method: 'POST' });
      topicPages[topicId] = 1;
      const details = document.querySelector(`#intelTopicItems-${topicId}`)?.closest('details');
      if (details) {
        delete details.dataset.loaded;
        if (details.open) loadTopicItems(topicId, 1);
      }
      await loadTopics();
      await refreshLoginStatus();
      alert(result.message || '运行完成');
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

  function exportTopicPack(topicId, topicName) {
    const a = document.createElement('a');
    a.href = `${API}/watch-topics/${topicId}/export.md`;
    a.download = `${topicName || '选题'}-选题包.md`;
    a.click();
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

    const filterSection = el('section', { class: 'panel' });
    filterSection.appendChild(el('div', { class: 'panel-head' }, ['多维选题挖掘']));
    const filterBody = el('div', { class: 'panel-body' });
    filterBody.appendChild(
      el('p', { class: 'hint', style: 'margin:0 0 10px;line-height:1.55;' }, [
        '不仅看关键词，还按功能场景、同类产品对比、多工具联动等 9 个维度分析已采集爆款，并给出可执行的搜索词建议。',
      ])
    );
    const topicSel = el('select', {
      id: 'intelMiningTopic',
      style: inputStyle('200px'),
      onchange: () => loadMiningInsights(),
    }, [el('option', { value: '' }, ['全部选题'])]);
    filterBody.appendChild(
      el('div', { style: 'display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap;' }, [
        el('span', { class: 'hint', style: 'margin:0;' }, ['分析范围：']),
        topicSel,
        el('button', { class: 'btn-secondary btn-small', onclick: loadMiningInsights }, ['刷新分析']),
      ])
    );
    filterBody.appendChild(el('p', { id: 'intelMiningNote', class: 'hint', style: 'margin:0 0 8px;' }, []));
    filterBody.appendChild(el('div', { id: 'intelMiningAngles' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    filterSection.appendChild(filterBody);
    panel.appendChild(filterSection);

    const sceneSection = el('section', { class: 'panel', style: 'margin-top:14px' });
    sceneSection.appendChild(el('div', { class: 'panel-head' }, ['场景词矩阵（人群×场景）']));
    sceneSection.appendChild(el('div', { class: 'panel-body', id: 'intelSceneMatrix' }, [el('p', { class: 'hint' }, ['—'])]));
    panel.appendChild(sceneSection);

    const s1 = el('section', { class: 'panel', style: 'margin-top:14px' });
    s1.appendChild(el('div', { class: 'panel-head' }, ['关键词补充建议']));
    const s1b = el('div', { class: 'panel-body' });
    s1b.appendChild(el('p', { class: 'hint', style: 'margin:0 0 8px;' }, ['从小红书相关搜索与标题词频挖掘的补充词，可与上方维度分析配合使用。']));
    s1b.appendChild(el('div', { id: 'intelSuggestTable' }, [el('p', { class: 'hint' }, ['—'])]));
    s1.appendChild(s1b);
    panel.appendChild(s1);

    const s2 = el('section', { class: 'panel', style: 'margin-top:14px' });
    s2.appendChild(el('div', { class: 'panel-head' }, ['跨选题对标']));
    s2.appendChild(el('div', { class: 'panel-body', id: 'intelBenchmarkTable' }, [el('p', { class: 'hint' }, ['—'])]));
    panel.appendChild(s2);

    populateMiningTopicSelect(topicSel);
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
    const sceneEl = document.getElementById('intelSceneMatrix');
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
      const [mining, suggestions] = await Promise.all([
        api(`/mining/insights${qs}`),
        api('/suggestions?limit=15'),
      ]);
      if (noteEl) {
        noteEl.textContent = `${mining.scope} · 共 ${mining.total_items} 条爆款 · ${mining.methodology_note || ''}`;
      }
      renderMiningAngles(anglesEl, mining.angles || []);
      renderSceneMatrix(sceneEl, mining.scene_matrix || [], mining.base_keywords || []);
      renderSuggestTable(document.getElementById('intelSuggestTable'), suggestions.items || []);
    } catch (e) {
      anglesEl.innerHTML = '';
      const msg = /404|Not Found/i.test(e.message)
        ? '接口不存在（Not Found）：服务可能未重启到 v1.12.0。请运行 ./open_app.sh 后强制刷新页面（Cmd+Shift+R）。'
        : `分析失败：${e.message}`;
      anglesEl.appendChild(el('p', { class: 'hint', style: 'color:var(--err);' }, [msg]));
    }
  }

  function renderMiningAngles(container, angles) {
    container.innerHTML = '';
    if (!angles.length) {
      container.appendChild(el('p', { class: 'hint' }, ['暂无数据，请先在「选题建立」运行采集。']));
      return;
    }
    const grid = el('div', { style: 'display:flex;flex-direction:column;gap:12px;' });
    angles.forEach((a) => {
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
      card.appendChild(el('p', { class: 'hint', style: 'margin:0 0 8px;font-size:12px;' }, [a.mechanism]));

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

      if (a.suggested_title) {
        card.appendChild(el('div', { style: 'font-size:12.5px;color:var(--accent);margin-bottom:8px;' }, [
          `仿写参考：${a.suggested_title}`,
        ]));
      }

      const evidence = a.top_evidence || [];
      if (evidence.length) {
        const details = el('details', { style: 'margin-top:4px;' });
        details.appendChild(el('summary', { style: 'cursor:pointer;font-size:12.5px;color:var(--accent);' }, [
          `查看佐证爆款（${evidence.length} 条）`,
        ]));
        const ul = el('ul', { style: 'margin:8px 0 0;padding-left:18px;font-size:12.5px;line-height:1.5;' });
        evidence.forEach((ev) => {
          ul.appendChild(el('li', { style: 'margin-bottom:4px;' }, [
            el('a', { href: ev.url, target: '_blank', style: 'color:var(--text);' }, [ev.title || '(无标题)']),
            ` · 赞${fmtNum(ev.liked_count)} · ${ev.content_type || ''}`,
          ]));
        });
        details.appendChild(ul);
        card.appendChild(details);
      }
      grid.appendChild(card);
    });
    container.appendChild(grid);
  }

  function renderSceneMatrix(container, rows, bases) {
    if (!container) return;
    container.innerHTML = '';
    if (!rows.length) {
      container.appendChild(el('p', { class: 'hint' }, ['暂无场景词，多采集功能场景类爆款后会出现。']));
      return;
    }
    const table = el('table', { class: 'show' });
    table.appendChild(el('thead', {}, [el('tr', {}, [
      el('th', {}, ['场景词']), el('th', {}, ['出现次数']), el('th', {}, ['建议选题搜索词']), el('th', {}, ['操作']),
    ])]));
    const tbody = el('tbody');
    rows.forEach((r) => {
      tbody.appendChild(el('tr', {}, [
        el('td', { style: 'font-weight:600;' }, [r.scene]),
        el('td', {}, [String(r.count)]),
        el('td', { style: 'font-size:12.5px;' }, [r.suggestion]),
        el('td', {}, [
          el('button', { class: 'btn-primary btn-small', onclick: () => createTopicFromMining(r.suggestion, `场景-${r.scene}`) }, ['创建选题']),
        ]),
      ]));
    });
    table.appendChild(tbody);
    container.appendChild(table);
    if (bases.length) {
      container.appendChild(el('p', { class: 'hint', style: 'margin-top:8px;' }, [
        `基础词：${bases.join('、')}`,
      ]));
    }
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
  // Tab: 数据追踪
  // ---------------------------------------------------------------------

  function renderTrackedTab() {
    const panel = document.getElementById('intelTabTracked');
    panel.innerHTML = '';
    const section = el('section', { class: 'panel' });
    section.appendChild(el('div', { class: 'panel-head' }, ['自有内容追踪']));
    const body = el('div', { class: 'panel-body' });

    body.appendChild(el('p', { class: 'hint', style: 'margin:0 0 10px;' }, [
      '粘贴已发布的小红书/视频号链接，系统会定期抓取转赞评藏数据。点击表格行查看表现趋势图。',
    ]));

    const platformSel = el('select', { id: 'intelTrackedPlatform', style: inputStyle('100px') }, [
      el('option', { value: 'xhs' }, ['小红书']),
      el('option', { value: 'channels' }, ['视频号']),
    ]);
    const urlInput = el('input', { id: 'intelTrackedUrl', placeholder: '发布后的笔记/视频链接', style: inputStyle('280px') });
    const accountInput = el('input', { id: 'intelTrackedAccount', placeholder: '账号名（可选）', style: inputStyle('140px') });
    body.appendChild(
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;' }, [
        platformSel, urlInput, accountInput,
        el('button', { class: 'btn-primary btn-small', onclick: addTrackedPost }, ['添加并抓取']),
        el('button', { class: 'btn-secondary btn-small', onclick: refreshAllTracked }, ['全部刷新']),
      ])
    );
    body.appendChild(el('p', { id: 'intelTrackedMsg', class: 'hint', style: 'margin:0 0 10px;' }, []));
    body.appendChild(el('div', { id: 'intelTrackedTable' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    body.appendChild(el('canvas', { id: 'intelTrackedChart', height: '100', style: 'margin-top:14px;max-height:220px;' }));
    body.appendChild(el('p', { id: 'intelTrackedChartHint', class: 'hint', style: 'margin-top:8px;' }, [
      '点击上方列表中的内容，查看点赞/收藏/评论/分享趋势。',
    ]));
    section.appendChild(body);
    panel.appendChild(section);
  }

  async function loadTracked() {
    const tableEl = document.getElementById('intelTrackedTable');
    if (!tableEl) return;
    try {
      const data = await api('/tracked');
      const items = data.items || [];
      tableEl.innerHTML = '';
      if (!items.length) {
        tableEl.appendChild(el('p', { class: 'hint' }, ['还没有追踪内容，在上方添加发布链接。']));
        return;
      }
      const table = el('table', { class: 'show' });
      table.appendChild(el('thead', {}, [el('tr', {}, [
        el('th', {}, ['平台']), el('th', {}, ['标题']), el('th', {}, ['转']), el('th', {}, ['赞']),
        el('th', {}, ['评']), el('th', {}, ['藏']), el('th', {}, ['最近刷新']), el('th', {}, ['操作']),
      ])]));
      const tbody = el('tbody');
      items.forEach((post) => {
        const m = postMetrics(post);
        const err = post.last_error;
        const tr = el('tr', {
          style: 'cursor:pointer;',
          onclick: (ev) => {
            if (ev.target.closest('button')) return;
            showTrackedHistory(post);
          },
        }, [
          el('td', {}, [post.platform === 'xhs' ? '小红书' : '视频号']),
          el('td', {}, [
            el('a', { href: post.url, target: '_blank', style: 'color:var(--accent);', onclick: (e) => e.stopPropagation() }, [
              post.title || post.url,
            ]),
            err ? el('div', { style: 'font-size:11px;color:var(--err);margin-top:2px;' }, [err.slice(0, 60)]) : null,
          ]),
          el('td', {}, [fmtNum(m.share)]),
          el('td', { style: 'font-weight:600;color:var(--accent);' }, [fmtNum(m.liked)]),
          el('td', {}, [fmtNum(m.comment)]),
          el('td', {}, [fmtNum(m.collected)]),
          el('td', { style: 'font-size:11.5px;color:var(--muted);' }, [post.last_refreshed_at || '-']),
          el('td', { style: 'display:flex;gap:4px;', onclick: (e) => e.stopPropagation() }, [
            el('button', { class: 'btn-secondary btn-small', onclick: () => refreshTracked(post.id) }, ['刷新']),
            el('button', { class: 'btn-danger btn-small', onclick: () => deleteTracked(post.id) }, ['删除']),
          ]),
        ]);
        if (selectedTrackedId === post.id) tr.style.background = 'var(--panel-2)';
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      tableEl.appendChild(table);
    } catch (e) {
      tableEl.innerHTML = '';
      tableEl.appendChild(el('p', { class: 'hint', style: 'color:var(--err);' }, [`加载失败：${e.message}`]));
    }
  }

  async function showTrackedHistory(post) {
    selectedTrackedId = post.id;
    const hint = document.getElementById('intelTrackedChartHint');
    if (hint) hint.textContent = `趋势图：${post.title || post.url}`;
    await loadTracked();
    try {
      const data = await api(`/tracked/${post.id}/history`);
      const history = data.items || [];
      await ensureChartJs();
      const ctx = document.getElementById('intelTrackedChart');
      if (!ctx) return;
      if (trackedChart) trackedChart.destroy();
      if (!history.length) {
        if (hint) hint.textContent = '暂无历史快照，点「刷新」后再查看趋势。';
        return;
      }
      trackedChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: history.map((h) => (h.captured_at || '').slice(5, 16)),
          datasets: [
            { label: '点赞', data: history.map((h) => h.liked_count), borderColor: '#2f7bff', tension: 0.25 },
            { label: '收藏', data: history.map((h) => h.collected_count), borderColor: '#22b07d', tension: 0.25 },
            { label: '评论', data: history.map((h) => h.comment_count), borderColor: '#eb9a2b', tension: 0.25 },
            { label: '分享', data: history.map((h) => h.share_count), borderColor: '#eb5757', tension: 0.25 },
          ],
        },
        options: { responsive: true, plugins: { legend: { position: 'bottom' } } },
      });
    } catch (e) {
      if (hint) hint.textContent = `趋势加载失败：${e.message}`;
    }
  }

  async function addTrackedPost() {
    const msgEl = document.getElementById('intelTrackedMsg');
    const platform = document.getElementById('intelTrackedPlatform').value;
    const url = document.getElementById('intelTrackedUrl').value.trim();
    const account_name = (document.getElementById('intelTrackedAccount').value || '').trim();
    if (!url) { msgEl.textContent = '请填写链接'; return; }
    msgEl.textContent = '抓取中…';
    try {
      const post = await api('/tracked', { method: 'POST', body: JSON.stringify({ platform, url, account_name }) });
      document.getElementById('intelTrackedUrl').value = '';
      const m = postMetrics(post);
      if (post.last_error) {
        msgEl.textContent = `已添加，但抓取失败：${post.last_error}`;
        msgEl.style.color = 'var(--err)';
      } else {
        msgEl.textContent = `已添加 · 赞 ${fmtNum(m.liked)} 藏 ${fmtNum(m.collected)} 评 ${fmtNum(m.comment)}`;
        msgEl.style.color = 'var(--ok)';
      }
      await loadTracked();
      if (post.id) showTrackedHistory(post);
    } catch (e) {
      msgEl.textContent = `失败：${e.message}`;
      msgEl.style.color = 'var(--err)';
    }
  }

  async function refreshTracked(postId) {
    try {
      const post = await api(`/tracked/${postId}/refresh`, { method: 'POST' });
      await loadTracked();
      if (post.last_error) alert(`刷新失败：${post.last_error}`);
      else showTrackedHistory(post);
    } catch (e) { alert(`刷新失败：${e.message}`); }
  }

  async function refreshAllTracked() {
    try {
      await api('/tracked/refresh-all', { method: 'POST' });
      await loadTracked();
    } catch (e) { alert(`刷新失败：${e.message}`); }
  }

  async function deleteTracked(postId) {
    if (!confirm('确定删除？')) return;
    try {
      await api(`/tracked/${postId}`, { method: 'DELETE' });
      if (selectedTrackedId === postId) {
        selectedTrackedId = null;
        if (trackedChart) { trackedChart.destroy(); trackedChart = null; }
      }
      await loadTracked();
    } catch (e) { alert(`删除失败：${e.message}`); }
  }

  function init() {
    if (inited && document.getElementById('intelTabTopics')) {
      if (currentIntelTab === 'topics') loadTopics();
      if (currentIntelTab === 'mining') { loadMiningInsights(); loadBenchmark(); }
      if (currentIntelTab === 'tracked') loadTracked();
      refreshLoginStatus();
      return;
    }
    inited = true;
    renderShell();
  }

  window.IntelApp = { init };
})();
