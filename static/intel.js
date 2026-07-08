/* 内容情报 (Content Intelligence Hub) — hot-topic radar + owned-content tracking.
 * Self-contained module mirroring the ChannelsApp pattern: renders into #intelApp
 * and exposes window.IntelApp.init() for lazy first-render on tab switch.
 */
(function () {
  const API = '/api/intel';
  let inited = false;
  let topics = [];
  let currentTopicId = '';
  let currentPlatform = '';
  let radarChart = null;
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

  function renderItemCards(items, opts) {
    opts = opts || {};
    const wrap = el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;' });
    if (!items || !items.length) {
      wrap.appendChild(el('p', { class: 'hint' }, [opts.emptyText || '暂无样例数据']));
      return wrap;
    }
    items.forEach((item) => {
      const cover = item.cover_url
        ? el('img', { src: item.cover_url, style: 'width:100%;height:100px;object-fit:cover;border-radius:8px 8px 0 0;background:var(--panel-2);' })
        : el('div', { style: 'width:100%;height:100px;border-radius:8px 8px 0 0;background:var(--panel-2);display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:12px;' }, [
            item.platform === 'channels' ? '视频号' : '小红书',
          ]);
      const card = el('a', {
        href: item.url,
        target: '_blank',
        style: 'display:block;width:150px;border:1px solid var(--border);border-radius:8px;overflow:hidden;text-decoration:none;color:var(--text);background:var(--panel);',
      }, [
        cover,
        el('div', { style: 'padding:6px 8px;' }, [
          el('div', { style: 'font-size:12px;line-height:1.4;max-height:2.8em;overflow:hidden;margin-bottom:4px;' }, [item.title || '(无标题)']),
          el('div', { class: 'hint', style: 'font-size:11px;' }, [
            `赞${fmtNum(item.liked_count)} 藏${fmtNum(item.collected_count)} 评${fmtNum(item.comment_count)}`,
          ]),
        ]),
      ]);
      wrap.appendChild(card);
    });
    return wrap;
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

  function renderShell() {
    const root = document.getElementById('intelApp');
    root.innerHTML = '';

    const desc = el('p', { class: 'hint', style: 'margin:0 0 6px' }, [
      '自动追踪小红书/视频号热点选题，并可为已发布的自有内容登记链接、持续回抓表现数据。数据落地在本地 SQLite（output/intel.db），预留了对接物料生产平台的 API（见 docs/INTEL_PLATFORM_INTEGRATION.md）。',
    ]);
    root.appendChild(desc);
    root.appendChild(
      el('p', { class: 'hint', style: 'margin:0 0 14px;color:var(--accent);' }, [
        '提示：小红书的热点抓取与「小红书」Tab 里的「关键词/账号发现」共用同一个 Chrome 登录态（CDP）。如果选题运行后一直「新增 0 条」，通常是尚未登录小红书或登录已过期——先去「小红书」Tab 做一次关键词发现完成登录，再回来运行选题；「最近一次运行」列会显示具体原因。',
      ])
    );
    root.appendChild(
      el('div', { style: 'margin:0 0 12px;' }, [
        el('button', { class: 'btn-secondary btn-small', id: 'intelXhsLoginBtn', onclick: triggerXhsLoginFromIntel }, ['一键登录小红书（CDP）']),
      ])
    );

    root.appendChild(renderTopicsSection());
    root.appendChild(renderSuggestionsSection());
    root.appendChild(renderRadarSection());
    root.appendChild(renderAnalyticsSection());
    root.appendChild(renderTrackedSection());

    // Only safe to query by id (loadRadar/loadTracked/etc use document.getElementById)
    // once these sections are actually attached to the live document.
    loadSuggestions();
    loadRadar();
    loadAnalyticsOverview();
    loadTracked();
  }

  // ---------------------------------------------------------------------
  // Watch topics
  // ---------------------------------------------------------------------

  function renderTopicsSection() {
    const section = el('section', { class: 'panel', style: 'margin-bottom:18px' });
    section.appendChild(el('div', { class: 'panel-head' }, ['热点选题 / 定时抓取']));
    const body = el('div', { class: 'panel-body' });

    const nameInput = el('input', { id: 'intelTopicName', placeholder: '选题名称，如「AI 效率工具」', style: inputStyle() });
    const kwInput = el('input', { id: 'intelTopicKeywords', placeholder: '关键词，逗号分隔，如：AI效率,桌面Agent', style: inputStyle() });
    const xhsCheck = el('input', { type: 'checkbox', id: 'intelTopicXhs', checked: 'checked' });
    const chCheck = el('input', { type: 'checkbox', id: 'intelTopicChannels' });
    const limitInput = el('input', { id: 'intelTopicLimit', type: 'number', value: '20', min: '1', max: '50', style: inputStyle('90px') });
    const intervalInput = el('input', { id: 'intelTopicInterval', type: 'number', value: '360', min: '15', style: inputStyle('90px') });
    const minLikedInput = el('input', { id: 'intelTopicMinLiked', type: 'number', value: '0', min: '0', style: inputStyle('80px') });
    const minCollectedInput = el('input', { id: 'intelTopicMinCollected', type: 'number', value: '0', min: '0', style: inputStyle('80px') });
    const minCommentsInput = el('input', { id: 'intelTopicMinComments', type: 'number', value: '0', min: '0', style: inputStyle('80px') });
    const SORT_ROUND_OPTIONS = ['综合', '最新', '最多点赞', '最多评论', '最多收藏'];
    const sortChecks = SORT_ROUND_OPTIONS.map((label, idx) =>
      el('label', { class: 'checkbox-row', style: 'margin:0;font-size:12.5px;' }, [
        el('input', { type: 'checkbox', class: 'intelTopicSortRound', value: label, checked: idx === 0 ? 'checked' : undefined }),
        ` ${label}`,
      ])
    );
    const noteTypeSelect = el('select', { id: 'intelTopicNoteType', style: inputStyle('110px') }, [
      el('option', { value: '' }, ['类型 · 不限']),
      el('option', { value: '视频' }, ['类型 · 视频']),
      el('option', { value: '图文' }, ['类型 · 图文']),
    ]);
    const accountInput = el('input', { id: 'intelTopicAccount', placeholder: 'CDP 账号名（可选，同「发现」页）', style: inputStyle('220px') });

    const form = el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:8px;' }, [
      nameInput,
      kwInput,
      el('label', { class: 'checkbox-row', style: 'margin:0' }, [xhsCheck, ' 小红书']),
      el('label', { class: 'checkbox-row', style: 'margin:0' }, [chCheck, ' 视频号']),
      el('label', { class: 'checkbox-row', style: 'margin:0' }, ['每次抓取', limitInput, '条']),
      el('label', { class: 'checkbox-row', style: 'margin:0' }, ['间隔', intervalInput, '分钟']),
      el('button', { class: 'btn-primary', onclick: createTopic }, ['创建选题']),
    ]);
    const form2 = el(
      'div',
      { style: 'display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-bottom:6px;' },
      [
        el('span', { class: 'hint', style: 'margin:0;' }, ['多轮采集（勾选多个=每个关键词多搜几轮，覆盖更多爆款）：']),
        ...sortChecks,
      ]
    );
    const form3 = el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px;' }, [
      noteTypeSelect,
      el('label', { class: 'checkbox-row', style: 'margin:0' }, ['最低赞', minLikedInput]),
      el('label', { class: 'checkbox-row', style: 'margin:0' }, ['最低藏', minCollectedInput]),
      el('label', { class: 'checkbox-row', style: 'margin:0' }, ['最低评', minCommentsInput]),
      accountInput,
    ]);
    body.appendChild(form);
    body.appendChild(form2);
    body.appendChild(form3);
    body.appendChild(el('p', { id: 'intelTopicCreateMsg', class: 'hint', style: 'margin:0 0 10px' }, []));

    body.appendChild(el('div', { id: 'intelTopicList' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    section.appendChild(body);

    loadTopics(section);
    return section;
  }

  function isRunMessageWarning(msg) {
    if (!msg) return false;
    return /错误|失败|未登录|login|error/i.test(msg);
  }

  function inputStyle(width) {
    return `padding:8px 10px;border-radius:10px;border:1px solid var(--border);background:var(--panel);color:var(--text);${width ? `width:${width};` : 'flex:1 1 200px;'}`;
  }

  async function triggerXhsLoginFromIntel(ev) {
    const btn = ev && ev.currentTarget ? ev.currentTarget : document.getElementById('intelXhsLoginBtn');
    if (!btn) return;
    const old = btn.textContent;
    btn.disabled = true;
    btn.textContent = '正在唤起登录…';
    try {
      const statusResp = await fetch('/api/xhs/login-status');
      const status = await statusResp.json().catch(() => ({}));
      if (!statusResp.ok) {
        throw new Error(status.detail || `登录状态检测失败 (${statusResp.status})`);
      }
      if (status.logged_in) {
        alert('小红书当前已登录，可直接运行选题。');
        return;
      }
      const loginResp = await fetch('/api/xhs/login', { method: 'POST' });
      const r = await loginResp.json().catch(() => ({}));
      if (!loginResp.ok) {
        throw new Error(r.detail || `触发登录失败 (${loginResp.status})`);
      }
      alert(r.message || '已唤起登录流程，请在 Chrome 中完成登录后再回来运行选题。');
    } catch (e) {
      alert(`触发登录失败：${e.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  async function loadTopics(section) {
    const listEl = section.querySelector('#intelTopicList');
    try {
      const data = await api('/watch-topics');
      topics = data.items || [];
    } catch (e) {
      listEl.innerHTML = '';
      listEl.appendChild(el('p', { class: 'hint' }, [`加载选题失败：${e.message}`]));
      return;
    }
    renderTopicList(listEl);
    populateTopicFilter();
  }

  function renderTopicList(listEl) {
    listEl.innerHTML = '';
    if (!topics.length) {
      listEl.appendChild(el('p', { class: 'hint' }, ['还没有选题，创建一个开始自动追踪热点吧。']));
      return;
    }
    const table = el('table', { class: 'show' });
    table.appendChild(
      el('thead', {}, [
        el('tr', {}, [
          el('th', {}, ['名称']),
          el('th', {}, ['平台']),
          el('th', {}, ['关键词']),
          el('th', {}, ['间隔']),
          el('th', {}, ['状态']),
          el('th', {}, ['最近一次运行']),
          el('th', {}, ['操作']),
        ]),
      ])
    );
    const tbody = el('tbody');
    topics.forEach((t) => {
      const platformsLabel = (t.platforms || []).map((p) => (p === 'xhs' ? '小红书' : '视频号')).join('/');
      tbody.appendChild(
        el('tr', {}, [
          el('td', {}, [t.name]),
          el('td', {}, [platformsLabel || '-']),
          el('td', {}, [
            (t.keywords || []).join('、'),
            (t.filters && t.filters.sort_rounds && t.filters.sort_rounds.length > 1)
              ? el('span', { class: 'hint', style: 'display:block;' }, [`每词 ${t.filters.sort_rounds.length} 轮：${t.filters.sort_rounds.join('/')}`])
              : null,
          ]),
          el('td', {}, [`${t.interval_minutes} 分钟`]),
          el(
            'td',
            {},
            [t.enabled ? '✅ 启用' : '⏸ 停用']
          ),
          el(
            'td',
            { style: isRunMessageWarning(t.last_run_message) ? 'color:var(--err);' : '' },
            [t.last_run_message ? `${t.last_run_at || ''} · ${t.last_run_message}` : '尚未运行']
          ),
          el('td', { style: 'display:flex;gap:6px;flex-wrap:wrap;' }, [
            el('button', { class: 'btn-secondary btn-small', onclick: (ev) => runTopicNow(t.id, ev.currentTarget) }, ['运行一次']),
            el('button', { class: 'btn-secondary btn-small', onclick: () => toggleTopic(t) }, [t.enabled ? '停用' : '启用']),
            el('button', { class: 'btn-danger btn-small', onclick: () => deleteTopic(t.id) }, ['删除']),
          ]),
        ])
      );
    });
    table.appendChild(tbody);
    listEl.appendChild(table);
  }

  async function createTopic() {
    const msgEl = document.getElementById('intelTopicCreateMsg');
    const name = document.getElementById('intelTopicName').value.trim();
    const keywords = document.getElementById('intelTopicKeywords').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    const platforms = [];
    if (document.getElementById('intelTopicXhs').checked) platforms.push('xhs');
    if (document.getElementById('intelTopicChannels').checked) platforms.push('channels');
    const limit_per_run = Number(document.getElementById('intelTopicLimit').value || 20);
    const interval_minutes = Number(document.getElementById('intelTopicInterval').value || 360);
    const sortRounds = Array.from(document.querySelectorAll('.intelTopicSortRound:checked')).map((el) => el.value);
    const filters = {
      min_liked: Number(document.getElementById('intelTopicMinLiked').value || 0),
      min_collected: Number(document.getElementById('intelTopicMinCollected').value || 0),
      min_comments: Number(document.getElementById('intelTopicMinComments').value || 0),
      sort_rounds: sortRounds,
      note_type: document.getElementById('intelTopicNoteType').value || '',
      account: document.getElementById('intelTopicAccount').value.trim(),
    };

    if (!name || !keywords.length || !platforms.length) {
      msgEl.textContent = '请填写选题名称、至少一个关键词，并选择至少一个平台';
      msgEl.style.color = 'var(--err)';
      return;
    }
    try {
      await api('/watch-topics', {
        method: 'POST',
        body: JSON.stringify({ name, keywords, platforms, limit_per_run, interval_minutes, filters }),
      });
      document.getElementById('intelTopicName').value = '';
      document.getElementById('intelTopicKeywords').value = '';
      msgEl.textContent = `已创建选题「${name}」，点击「运行一次」立即抓取，或等待自动定时运行。`;
      msgEl.style.color = 'var(--ok)';
      await loadTopics(document.getElementById('intelApp').querySelector('.panel'));
    } catch (e) {
      msgEl.textContent = `创建失败：${e.message}`;
      msgEl.style.color = 'var(--err)';
    }
  }

  async function runTopicNow(topicId, btn) {
    const originalText = btn ? btn.textContent : '';
    if (btn) {
      btn.disabled = true;
      btn.textContent = '运行中…';
    }
    try {
      const result = await api(`/watch-topics/${topicId}/run`, { method: 'POST' });
      alert(`运行完成：${result.message}`);
      const section = document.getElementById('intelApp').querySelector('.panel');
      await loadTopics(section);
      await loadRadar();
    } catch (e) {
      alert(`运行失败：${e.message}`);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    }
  }

  async function toggleTopic(t) {
    try {
      await api(`/watch-topics/${t.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !t.enabled }) });
      await loadTopics(document.getElementById('intelApp').querySelector('.panel'));
    } catch (e) {
      alert(`更新失败：${e.message}`);
    }
  }

  async function deleteTopic(topicId) {
    if (!confirm('确定删除该选题吗？（已抓取的雷达数据会保留）')) return;
    try {
      await api(`/watch-topics/${topicId}`, { method: 'DELETE' });
      await loadTopics(document.getElementById('intelApp').querySelector('.panel'));
    } catch (e) {
      alert(`删除失败：${e.message}`);
    }
  }

  function populateTopicFilter() {
    const sel = document.getElementById('intelRadarTopic');
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '';
    sel.appendChild(el('option', { value: '' }, ['全部选题']));
    topics.forEach((t) => sel.appendChild(el('option', { value: t.id }, [t.name])));
    sel.value = topics.some((t) => t.id === prev) ? prev : '';
  }

  // ---------------------------------------------------------------------
  // 选题建议 (keyword suggestions)
  // ---------------------------------------------------------------------

  function renderSuggestionsSection() {
    const section = el('section', { class: 'panel', style: 'margin-bottom:18px' });
    section.appendChild(el('div', { class: 'panel-head' }, ['选题建议']));
    const body = el('div', { class: 'panel-body' });
    body.appendChild(
      el('p', { class: 'hint', style: 'margin:0 0 10px' }, [
        '两个来源：① 小红书搜索时自带的"相关搜索词"，选题运行得越多，这里积累得越准；② 对已抓到的爆款标题做关键词挖掘（本地计算，不额外调用接口）。点"查看证据"能看到支撑这个建议的具体爆款内容，点"创建为选题"一键把它变成新的追踪选题。',
      ])
    );
    body.appendChild(
      el('div', { style: 'display:flex;gap:10px;align-items:center;margin-bottom:10px;' }, [
        el('button', { class: 'btn-secondary btn-small', onclick: loadSuggestions }, ['刷新建议']),
      ])
    );
    body.appendChild(el('div', { id: 'intelSuggestTable' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    body.appendChild(el('div', { id: 'intelSuggestEvidence' }));
    section.appendChild(body);
    return section;
  }

  async function loadSuggestions() {
    const tableEl = document.getElementById('intelSuggestTable');
    if (!tableEl) return;
    let items = [];
    try {
      const data = await api('/suggestions?limit=30');
      items = data.items || [];
    } catch (e) {
      tableEl.innerHTML = '';
      tableEl.appendChild(el('p', { class: 'hint' }, [`加载失败：${e.message}`]));
      return;
    }
    renderSuggestTable(tableEl, items);
  }

  const SOURCE_LABELS = { xhs_related: '小红书相关搜索', mined: '爆款词频挖掘' };

  function renderSuggestTable(tableEl, items) {
    tableEl.innerHTML = '';
    if (!items.length) {
      tableEl.appendChild(
        el('p', { class: 'hint' }, ['暂无建议——先创建并运行几个选题，积累一些爆款数据后这里会自动出现推荐词。'])
      );
      return;
    }
    const table = el('table', { class: 'show' });
    table.appendChild(
      el('thead', {}, [
        el('tr', {}, [
          el('th', {}, ['建议关键词']),
          el('th', {}, ['来源']),
          el('th', {}, ['热度分']),
          el('th', {}, ['命中/佐证条数']),
          el('th', {}, ['操作']),
        ]),
      ])
    );
    const tbody = el('tbody');
    items.forEach((s) => {
      tbody.appendChild(
        el('tr', {}, [
          el('td', { style: 'font-weight:600;' }, [s.keyword]),
          el('td', {}, [(s.sources || []).map((k) => SOURCE_LABELS[k] || k).join(' + ')]),
          el('td', {}, [String(Math.round(s.score * 10) / 10)]),
          el('td', {}, [String(s.hit_count || (s.sample_item_ids || []).length)]),
          el('td', { style: 'display:flex;gap:6px;flex-wrap:wrap;' }, [
            el('button', {
              class: 'btn-secondary btn-small',
              onclick: (ev) => showSuggestionEvidence(s, ev.currentTarget),
            }, ['查看证据']),
            el('button', {
              class: 'btn-primary btn-small',
              onclick: (ev) => promoteSuggestion(s, ev.currentTarget),
            }, ['创建为选题']),
          ]),
        ])
      );
    });
    table.appendChild(tbody);
    tableEl.appendChild(table);
  }

  async function showSuggestionEvidence(suggestion, btn) {
    const box = document.getElementById('intelSuggestEvidence');
    if (!box) return;
    box.innerHTML = '';
    box.appendChild(el('p', { class: 'hint', style: 'margin:10px 0 0' }, [`「${suggestion.keyword}」的佐证爆款内容：`]));
    const ids = (suggestion.sample_item_ids || []).join(',');
    if (!ids) {
      box.appendChild(el('p', { class: 'hint' }, ['暂无本地样例（这是小红书返回的相关词，还没有被搜索过）。']));
      return;
    }
    try {
      const data = await api(`/suggestions/items?ids=${ids}`);
      box.appendChild(renderItemCards(data.items || []));
    } catch (e) {
      box.appendChild(el('p', { class: 'hint' }, [`加载证据失败：${e.message}`]));
    }
  }

  async function promoteSuggestion(suggestion, btn) {
    const originalText = btn ? btn.textContent : '';
    if (btn) {
      btn.disabled = true;
      btn.textContent = '创建中…';
    }
    try {
      await api('/suggestions/promote', {
        method: 'POST',
        body: JSON.stringify({ keyword: suggestion.keyword, platform: suggestion.platform || 'xhs' }),
      });
      alert(`已创建选题「${suggestion.keyword}」，可以在上方「热点选题」列表里点「运行一次」立即抓取。`);
      await loadTopics(document.getElementById('intelApp').querySelector('.panel'));
      await loadSuggestions();
    } catch (e) {
      alert(`创建失败：${e.message}`);
      if (btn) {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    }
  }

  // ---------------------------------------------------------------------
  // Radar
  // ---------------------------------------------------------------------

  function renderRadarSection() {
    const section = el('section', { class: 'panel', style: 'margin-bottom:18px' });
    section.appendChild(el('div', { class: 'panel-head' }, ['热点雷达']));
    const body = el('div', { class: 'panel-body' });

    const topicSel = el('select', { id: 'intelRadarTopic', style: inputStyle('180px'), onchange: onRadarFilterChange }, [
      el('option', { value: '' }, ['全部选题']),
    ]);
    const platformSel = el('select', { id: 'intelRadarPlatform', style: inputStyle('130px'), onchange: onRadarFilterChange }, [
      el('option', { value: '' }, ['全部平台']),
      el('option', { value: 'xhs' }, ['小红书']),
      el('option', { value: 'channels' }, ['视频号']),
    ]);
    body.appendChild(
      el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px;' }, [
        topicSel,
        platformSel,
        el('button', { class: 'btn-secondary btn-small', onclick: loadRadar }, ['刷新']),
      ])
    );

    body.appendChild(el('canvas', { id: 'intelRadarChart', height: '90' }));
    body.appendChild(el('div', { id: 'intelRadarTable', style: 'margin-top:14px;overflow:auto;' }, [
      el('p', { class: 'hint' }, ['加载中…']),
    ]));

    section.appendChild(body);
    return section;
  }

  function onRadarFilterChange() {
    currentTopicId = document.getElementById('intelRadarTopic').value;
    currentPlatform = document.getElementById('intelRadarPlatform').value;
    loadRadar();
  }

  async function loadRadar() {
    const tableEl = document.getElementById('intelRadarTable');
    const params = new URLSearchParams();
    if (currentTopicId) params.set('topic_id', currentTopicId);
    if (currentPlatform) params.set('platform', currentPlatform);
    let items = [];
    try {
      const data = await api(`/radar?${params.toString()}`);
      items = data.items || [];
    } catch (e) {
      tableEl.innerHTML = '';
      tableEl.appendChild(el('p', { class: 'hint' }, [`加载雷达数据失败：${e.message}`]));
      return;
    }
    renderRadarTable(tableEl, items);
    renderRadarChart(items.slice(0, 10));
  }

  function renderRadarTable(tableEl, items) {
    tableEl.innerHTML = '';
    if (!items.length) {
      tableEl.appendChild(el('p', { class: 'hint' }, ['暂无雷达数据，先创建选题并「运行一次」。']));
      return;
    }
    const table = el('table', { class: 'show' });
    table.appendChild(
      el('thead', {}, [
        el('tr', {}, [
          el('th', {}, ['#']),
          el('th', {}, ['平台']),
          el('th', {}, ['标题']),
          el('th', {}, ['作者']),
          el('th', {}, ['赞']),
          el('th', {}, ['藏']),
          el('th', {}, ['评']),
          el('th', {}, ['转']),
          el('th', {}, ['热度']),
          el('th', {}, ['关键词']),
          el('th', {}, ['最近更新']),
        ]),
      ])
    );
    const tbody = el('tbody');
    items.forEach((item, idx) => {
      tbody.appendChild(
        el('tr', {}, [
          el('td', {}, [String(idx + 1)]),
          el('td', {}, [item.platform === 'xhs' ? '小红书' : '视频号']),
          el('td', {}, [el('a', { href: item.url, target: '_blank', style: 'color:var(--accent);text-decoration:none;' }, [item.title || item.url])]),
          el('td', {}, [item.author || '-']),
          el('td', {}, [fmtNum(item.liked_count)]),
          el('td', {}, [fmtNum(item.collected_count)]),
          el('td', {}, [fmtNum(item.comment_count)]),
          el('td', {}, [fmtNum(item.share_count)]),
          el('td', { style: 'font-weight:700;color:var(--accent);' }, [String(item.hot_score)]),
          el('td', {}, [item.keyword || '-']),
          el('td', {}, [item.last_seen_at]),
        ])
      );
    });
    table.appendChild(tbody);
    tableEl.appendChild(table);
  }

  function renderRadarChart(topItems) {
    ensureChartJs()
      .then(() => {
        const ctx = document.getElementById('intelRadarChart');
        if (!ctx) return;
        const labels = topItems.map((i) => (i.title || i.url || '').slice(0, 14) || '(无标题)');
        const scores = topItems.map((i) => i.hot_score);
        if (radarChart) radarChart.destroy();
        radarChart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels,
            datasets: [{ label: '综合热度', data: scores, backgroundColor: 'rgba(47, 123, 255, 0.55)', borderRadius: 6 }],
          },
          options: {
            responsive: true,
            plugins: { legend: { display: false }, title: { display: true, text: '热点 TOP 10（综合热度）' } },
            scales: { x: { ticks: { autoSkip: false, maxRotation: 30, minRotation: 0 } } },
          },
        });
      })
      .catch(() => {});
  }

  // ---------------------------------------------------------------------
  // 数据分析 (analytics)
  // ---------------------------------------------------------------------

  let overviewChart = null;
  let noteTypeChart = null;
  let authorChart = null;
  let trendChart = null;

  function renderAnalyticsSection() {
    const section = el('section', { class: 'panel', style: 'margin-bottom:18px' });
    section.appendChild(el('div', { class: 'panel-head' }, ['数据分析']));
    const body = el('div', { class: 'panel-body' });

    body.appendChild(el('div', { id: 'intelOverviewStats', style: 'display:flex;gap:14px;flex-wrap:wrap;margin-bottom:12px;' }));
    body.appendChild(el('div', { id: 'intelOverviewTable' }, [el('p', { class: 'hint' }, ['加载中…'])]));

    body.appendChild(el('hr', { style: 'border:none;border-top:1px solid var(--border);margin:16px 0;' }));

    const topicSel = el(
      'select',
      { id: 'intelAnalyticsTopic', style: inputStyle('220px'), onchange: (ev) => loadTopicAnalytics(ev.target.value) },
      [el('option', { value: '' }, ['选择一个选题查看详细分析…'])]
    );
    body.appendChild(el('div', { style: 'display:flex;gap:10px;align-items:center;margin-bottom:12px;' }, [topicSel]));
    body.appendChild(el('div', { id: 'intelTopicAnalytics' }));

    section.appendChild(body);
    return section;
  }

  async function loadAnalyticsOverview() {
    const statsEl = document.getElementById('intelOverviewStats');
    const tableEl = document.getElementById('intelOverviewTable');
    const topicSel = document.getElementById('intelAnalyticsTopic');
    if (!statsEl || !tableEl) return;
    let data;
    try {
      data = await api('/analytics/overview');
    } catch (e) {
      tableEl.innerHTML = '';
      tableEl.appendChild(el('p', { class: 'hint' }, [`加载分析总览失败：${e.message}`]));
      return;
    }
    statsEl.innerHTML = '';
    [
      ['已收录爆款内容', data.total_items],
      ['待处理选题建议', data.total_suggestions],
      ['追踪中的自有内容', data.total_tracked_posts],
      ['选题数', (data.topics || []).length],
    ].forEach(([label, value]) => {
      statsEl.appendChild(
        el('div', { style: 'flex:1 1 140px;padding:12px 16px;border-radius:12px;background:var(--panel-2);' }, [
          el('div', { style: 'font-size:22px;font-weight:700;color:var(--accent);' }, [String(value ?? 0)]),
          el('div', { class: 'hint', style: 'margin-top:2px;' }, [label]),
        ])
      );
    });

    renderOverviewTable(tableEl, data.topics || []);

    if (topicSel) {
      const prev = topicSel.value;
      topicSel.innerHTML = '';
      topicSel.appendChild(el('option', { value: '' }, ['选择一个选题查看详细分析…']));
      (data.topics || []).forEach((t) => topicSel.appendChild(el('option', { value: t.id }, [t.name])));
      if ((data.topics || []).some((t) => t.id === prev)) topicSel.value = prev;
    }
  }

  function renderOverviewTable(tableEl, topics) {
    tableEl.innerHTML = '';
    if (!topics.length) {
      tableEl.appendChild(el('p', { class: 'hint' }, ['还没有选题，先在上方创建一个吧。']));
      return;
    }
    const table = el('table', { class: 'show' });
    table.appendChild(
      el('thead', {}, [
        el('tr', {}, [
          el('th', {}, ['选题']),
          el('th', {}, ['状态']),
          el('th', {}, ['爆款条数']),
          el('th', {}, ['视频占比']),
          el('th', {}, ['平均热度']),
          el('th', {}, ['峰值热度']),
          el('th', {}, ['最近一次运行']),
        ]),
      ])
    );
    const tbody = el('tbody');
    topics.forEach((t) => {
      const cnt = t.item_count || 0;
      const videoPct = cnt ? Math.round(((t.video_count || 0) / cnt) * 100) : 0;
      tbody.appendChild(
        el('tr', {}, [
          el('td', { style: 'font-weight:600;' }, [t.name]),
          el('td', {}, [t.enabled ? '✅ 启用' : '⏸ 停用']),
          el('td', {}, [String(cnt)]),
          el('td', {}, [cnt ? `${videoPct}%` : '-']),
          el('td', {}, [t.avg_hot_score ? String(Math.round(t.avg_hot_score * 10) / 10) : '-']),
          el('td', {}, [t.max_hot_score ? String(Math.round(t.max_hot_score * 10) / 10) : '-']),
          el('td', {}, [t.last_run_at || '尚未运行']),
        ])
      );
    });
    table.appendChild(tbody);
    tableEl.appendChild(table);
  }

  async function loadTopicAnalytics(topicId) {
    const box = document.getElementById('intelTopicAnalytics');
    if (!box) return;
    if (!topicId) {
      box.innerHTML = '';
      return;
    }
    box.innerHTML = '';
    box.appendChild(el('p', { class: 'hint' }, ['加载中…']));
    let data;
    try {
      data = await api(`/analytics/topics/${topicId}`);
    } catch (e) {
      box.innerHTML = '';
      box.appendChild(el('p', { class: 'hint' }, [`加载失败：${e.message}`]));
      return;
    }
    renderTopicAnalytics(box, data);
  }

  function renderTopicAnalytics(box, data) {
    box.innerHTML = '';
    const s = data.summary || {};
    if (!s.cnt) {
      box.appendChild(el('p', { class: 'hint' }, ['该选题还没有抓到数据，先运行一次试试。']));
      return;
    }

    const statsRow = el('div', { style: 'display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px;' });
    [
      ['爆款条数', s.cnt],
      ['平均点赞', fmtNum(Math.round(s.avg_liked || 0))],
      ['平均收藏', fmtNum(Math.round(s.avg_collected || 0))],
      ['平均评论', fmtNum(Math.round(s.avg_comment || 0))],
      ['最高热度', Math.round((s.max_hot || 0) * 10) / 10],
    ].forEach(([label, value]) => {
      statsRow.appendChild(
        el('div', { style: 'flex:1 1 110px;padding:10px 14px;border-radius:10px;background:var(--panel-2);' }, [
          el('div', { style: 'font-size:18px;font-weight:700;color:var(--accent);' }, [String(value)]),
          el('div', { class: 'hint', style: 'margin-top:2px;font-size:11.5px;' }, [label]),
        ])
      );
    });
    box.appendChild(statsRow);

    const chartsRow = el('div', { style: 'display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px;' }, [
      el('div', { style: 'flex:1 1 220px;min-width:200px;' }, [el('canvas', { id: 'intelNoteTypeChart', height: '180' })]),
      el('div', { style: 'flex:2 1 320px;min-width:280px;' }, [el('canvas', { id: 'intelAuthorChart', height: '180' })]),
    ]);
    box.appendChild(chartsRow);
    box.appendChild(el('canvas', { id: 'intelTrendChart', height: '80', style: 'margin-bottom:14px;' }));

    box.appendChild(el('p', { class: 'hint', style: 'margin:0 0 6px;font-weight:600;' }, ['该选题下的爆款 TOP 内容：']));
    box.appendChild(renderItemCards(data.top_items || []));

    ensureChartJs()
      .then(() => {
        const noteTypeCtx = document.getElementById('intelNoteTypeChart');
        if (noteTypeCtx) {
          if (noteTypeChart) noteTypeChart.destroy();
          const rows = data.note_type_breakdown || [];
          noteTypeChart = new Chart(noteTypeCtx, {
            type: 'pie',
            data: {
              labels: rows.map((r) => r.note_type),
              datasets: [{ data: rows.map((r) => r.cnt), backgroundColor: ['#2f7bff', '#22b07d', '#eb9a2b', '#eb5757'] }],
            },
            options: { responsive: true, plugins: { title: { display: true, text: '图文/视频占比' } } },
          });
        }

        const authorCtx = document.getElementById('intelAuthorChart');
        if (authorCtx) {
          if (authorChart) authorChart.destroy();
          const rows = (data.top_authors || []).slice(0, 8);
          authorChart = new Chart(authorCtx, {
            type: 'bar',
            data: {
              labels: rows.map((r) => r.author),
              datasets: [{ label: '累计热度', data: rows.map((r) => Math.round(r.total_score * 10) / 10), backgroundColor: 'rgba(34,176,125,0.6)', borderRadius: 6 }],
            },
            options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: '高产作者 TOP 8（累计热度）' } } },
          });
        }

        const trendCtx = document.getElementById('intelTrendChart');
        if (trendCtx) {
          if (trendChart) trendChart.destroy();
          const rows = data.daily_trend || [];
          trendChart = new Chart(trendCtx, {
            type: 'line',
            data: {
              labels: rows.map((r) => r.day),
              datasets: [{ label: '平均热度', data: rows.map((r) => Math.round(r.avg_hot * 10) / 10), borderColor: '#2f7bff', tension: 0.25, fill: false }],
            },
            options: { responsive: true, plugins: { title: { display: true, text: '每日平均热度趋势' } } },
          });
        }
      })
      .catch(() => {});
  }

  // ---------------------------------------------------------------------
  // Tracked (owned) posts
  // ---------------------------------------------------------------------

  function renderTrackedSection() {
    const section = el('section', { class: 'panel' });
    section.appendChild(el('div', { class: 'panel-head' }, ['自有内容追踪']));
    const body = el('div', { class: 'panel-body' });

    const platformSel = el('select', { id: 'intelTrackedPlatform', style: inputStyle('110px') }, [
      el('option', { value: 'xhs' }, ['小红书']),
      el('option', { value: 'channels' }, ['视频号']),
    ]);
    const urlInput = el('input', { id: 'intelTrackedUrl', placeholder: '发布后的笔记/视频链接', style: inputStyle() });
    const accountInput = el('input', { id: 'intelTrackedAccount', placeholder: '账号名（可选）', style: inputStyle('160px') });

    body.appendChild(
      el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px;' }, [
        platformSel,
        urlInput,
        accountInput,
        el('button', { class: 'btn-primary', onclick: addTrackedPost }, ['添加并抓取一次']),
        el('button', { class: 'btn-secondary', onclick: refreshAllTracked }, ['全部刷新']),
      ])
    );
    body.appendChild(el('p', { id: 'intelTrackedMsg', class: 'hint', style: 'margin:0 0 10px' }, []));

    body.appendChild(el('div', { id: 'intelTrackedTable' }, [el('p', { class: 'hint' }, ['加载中…'])]));
    body.appendChild(el('canvas', { id: 'intelTrackedChart', height: '90', style: 'margin-top:14px;' }));
    body.appendChild(el('p', { id: 'intelTrackedChartHint', class: 'hint' }, ['点击下方表格中的任意一行，查看该内容的表现趋势。']));

    section.appendChild(body);
    return section;
  }

  async function loadTracked() {
    const tableEl = document.getElementById('intelTrackedTable');
    let items = [];
    try {
      const data = await api('/tracked');
      items = data.items || [];
    } catch (e) {
      tableEl.innerHTML = '';
      tableEl.appendChild(el('p', { class: 'hint' }, [`加载失败：${e.message}`]));
      return;
    }
    renderTrackedTable(tableEl, items);
  }

  function renderTrackedTable(tableEl, items) {
    tableEl.innerHTML = '';
    if (!items.length) {
      tableEl.appendChild(el('p', { class: 'hint' }, ['还没有追踪任何自有内容，粘贴发布后的链接开始追踪表现吧。']));
      return;
    }
    const table = el('table', { class: 'show' });
    table.appendChild(
      el('thead', {}, [
        el('tr', {}, [
          el('th', {}, ['平台']),
          el('th', {}, ['标题']),
          el('th', {}, ['账号']),
          el('th', {}, ['赞']),
          el('th', {}, ['藏']),
          el('th', {}, ['评']),
          el('th', {}, ['转']),
          el('th', {}, ['最近刷新']),
          el('th', {}, ['状态']),
          el('th', {}, ['操作']),
        ]),
      ])
    );
    const tbody = el('tbody');
    items.forEach((post) => {
      const row = el('tr', { style: 'cursor:pointer;', onclick: () => showTrackedHistory(post) }, [
        el('td', {}, [post.platform === 'xhs' ? '小红书' : '视频号']),
        el('td', {}, [el('a', { href: post.url, target: '_blank', style: 'color:var(--accent);text-decoration:none;' }, [post.title || post.url])]),
        el('td', {}, [post.account_name || '-']),
        el('td', {}, [fmtNum(post.latest_liked)]),
        el('td', {}, [fmtNum(post.latest_collected)]),
        el('td', {}, [fmtNum(post.latest_comment)]),
        el('td', {}, [fmtNum(post.latest_share)]),
        el('td', {}, [post.last_refreshed_at || '-']),
        el(
          'td',
          { style: post.last_error ? 'color:var(--err);max-width:220px;' : 'color:var(--ok);' },
          [post.last_error ? `⚠ ${post.last_error}` : '✅ 正常']
        ),
        el('td', {}, [
          el('button', {
            class: 'btn-secondary btn-small',
            onclick: (ev) => {
              ev.stopPropagation();
              refreshTracked(post.id, ev.currentTarget);
            },
          }, ['刷新']),
          ' ',
          el('button', {
            class: 'btn-danger btn-small',
            onclick: (ev) => {
              ev.stopPropagation();
              deleteTracked(post.id);
            },
          }, ['删除']),
        ]),
      ]);
      if (post.last_error) {
        row.title = `上次刷新出错：${post.last_error}`;
      }
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    tableEl.appendChild(table);
  }

  async function addTrackedPost() {
    const msgEl = document.getElementById('intelTrackedMsg');
    const platform = document.getElementById('intelTrackedPlatform').value;
    const url = document.getElementById('intelTrackedUrl').value.trim();
    const account_name = document.getElementById('intelTrackedAccount').value.trim();
    if (!url) {
      msgEl.textContent = '请先填写发布后的笔记/视频链接';
      msgEl.style.color = 'var(--err)';
      return;
    }
    msgEl.textContent = '正在抓取该链接的最新数据…';
    msgEl.style.color = '';
    try {
      const post = await api('/tracked', { method: 'POST', body: JSON.stringify({ platform, url, account_name }) });
      document.getElementById('intelTrackedUrl').value = '';
      if (post.last_error) {
        msgEl.textContent = `已添加，但首次抓取失败：${post.last_error}（可稍后点「刷新」重试）`;
        msgEl.style.color = 'var(--err)';
      } else {
        msgEl.textContent = `已添加「${post.title || url}」，当前 赞${fmtNum(post.latest_liked)} 藏${fmtNum(post.latest_collected)} 评${fmtNum(post.latest_comment)}。`;
        msgEl.style.color = 'var(--ok)';
      }
      await loadTracked();
    } catch (e) {
      msgEl.textContent = `添加失败：${e.message}`;
      msgEl.style.color = 'var(--err)';
    }
  }

  async function refreshTracked(postId, btn) {
    const msgEl = document.getElementById('intelTrackedMsg');
    const originalText = btn ? btn.textContent : '';
    if (btn) {
      btn.disabled = true;
      btn.textContent = '刷新中…';
    }
    try {
      const post = await api(`/tracked/${postId}/refresh`, { method: 'POST' });
      if (post.last_error) {
        msgEl.textContent = `刷新失败：${post.last_error}`;
        msgEl.style.color = 'var(--err)';
      } else {
        msgEl.textContent = `刷新成功：赞${fmtNum(post.latest_liked)} 藏${fmtNum(post.latest_collected)} 评${fmtNum(post.latest_comment)}`;
        msgEl.style.color = 'var(--ok)';
      }
      await loadTracked();
    } catch (e) {
      msgEl.textContent = `刷新失败：${e.message}`;
      msgEl.style.color = 'var(--err)';
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    }
  }

  async function refreshAllTracked() {
    const msgEl = document.getElementById('intelTrackedMsg');
    msgEl.textContent = '正在全部刷新…';
    msgEl.style.color = '';
    try {
      const result = await api('/tracked/refresh-all', { method: 'POST' });
      const results = result.results || [];
      const ok = results.filter((r) => r.ok).length;
      const failMsgs = results.filter((r) => !r.ok).map((r) => r.error).filter(Boolean);
      msgEl.textContent = `刷新完成：${ok}/${results.length} 成功` + (failMsgs.length ? `；示例失败原因：${failMsgs[0]}` : '');
      msgEl.style.color = failMsgs.length ? 'var(--err)' : 'var(--ok)';
      await loadTracked();
    } catch (e) {
      msgEl.textContent = `刷新失败：${e.message}`;
      msgEl.style.color = 'var(--err)';
    }
  }

  async function deleteTracked(postId) {
    if (!confirm('确定停止追踪该内容吗？')) return;
    try {
      await api(`/tracked/${postId}`, { method: 'DELETE' });
      await loadTracked();
    } catch (e) {
      alert(`删除失败：${e.message}`);
    }
  }

  async function showTrackedHistory(post) {
    selectedTrackedId = post.id;
    document.getElementById('intelTrackedChartHint').textContent = `正在展示「${post.title || post.url}」的表现趋势`;
    let history = [];
    try {
      const data = await api(`/tracked/${post.id}/history`);
      history = data.items || [];
    } catch (e) {
      return;
    }
    ensureChartJs()
      .then(() => {
        const ctx = document.getElementById('intelTrackedChart');
        if (!ctx) return;
        const labels = history.map((h) => h.captured_at);
        if (trackedChart) trackedChart.destroy();
        trackedChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels,
            datasets: [
              { label: '点赞', data: history.map((h) => h.liked_count), borderColor: '#2f7bff', tension: 0.25 },
              { label: '收藏', data: history.map((h) => h.collected_count), borderColor: '#22b07d', tension: 0.25 },
              { label: '评论', data: history.map((h) => h.comment_count), borderColor: '#eb9a2b', tension: 0.25 },
              { label: '分享', data: history.map((h) => h.share_count), borderColor: '#eb5757', tension: 0.25 },
            ],
          },
          options: { responsive: true, plugins: { title: { display: false } } },
        });
      })
      .catch(() => {});
  }

  function init() {
    if (inited && document.getElementById('intelTopicList')) {
      loadTopics(document.getElementById('intelApp').querySelector('.panel'));
      loadSuggestions();
      loadRadar();
      loadAnalyticsOverview();
      loadTracked();
      return;
    }
    inited = true;
    renderShell();
  }

  window.IntelApp = { init };
})();
