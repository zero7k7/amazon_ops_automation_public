from __future__ import annotations

import base64
import zlib


def _inflate(payload: str) -> str:
    return zlib.decompress(base64.b64decode(payload)).decode("utf-8")

CSS = _inflate(
    "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"
)

REPORT_UI_CSS = _inflate(
    "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"
)

REPORT_UI_CSS += r"""
.ad-head-right {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
}
.ad-head-right .ad-feedback-refresh {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex: 1 1 100%;
  min-width: 220px;
}
.ad-head-right .ad-feedback-refresh .subtle {
  max-width: 280px;
  white-space: normal;
  text-align: right;
}
.ad-task-card {
  position: relative;
  padding-bottom: 48px;
}
.ad-task-card .ad-complete-row {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 24px;
  margin: 0;
}
.ad-task-card .ad-complete-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  line-height: 1.2;
  white-space: nowrap;
}
.ad-task-card [data-ad-complete-message] {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ad-copy-box {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ad-copy-box .ad-complete-row {
  position: static;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 22px;
  margin: 0;
  padding: 0 2px;
}
.ad-copy-box .ad-complete-control {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  line-height: 1.2;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
  white-space: nowrap;
}
.ad-copy-box .ad-complete-control input[type="checkbox"] {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  margin: 0;
}
.ad-copy-box [data-ad-complete-message] {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ad-section.is-copy-only-hidden,
.ad-task-grid.is-copy-only-hidden {
  display: none;
}
"""

REPORT_JS = _inflate(
    "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"
)

REPORT_JS += r"""

(function () {
  var ACTION_TOKEN_HEADER = 'X-Report-Action-Token';
  var ACTION_ENDPOINTS = {
    '/upload/today-data': true,
    '/upload/config': true,
    '/apply/config': true,
    '/copy/text': true,
    '/run/daily-update': true,
    '/run/frontend-retry': true,
    '/run/frontend-check-one': true,
    '/run/battle-diagnosis-one': true,
    '/feedback/ad-action-complete': true,
    '/feedback/ad-action-cancel': true
  };

  function reportActionToken() {
    var meta = document.querySelector('meta[name="report-action-token"]');
    return meta ? String(meta.getAttribute('content') || '').trim() : '';
  }

  function isLocalActionEndpoint(resource) {
    try {
      var rawUrl = typeof resource === 'string' ? resource : (resource && resource.url) || '';
      var url = new URL(rawUrl, window.location.href);
      var port = url.port || (url.protocol === 'https:' ? '443' : '80');
      var isLocalReportServer = (url.hostname === '127.0.0.1' || url.hostname === 'localhost') && port === '8765';
      return isLocalReportServer && !!ACTION_ENDPOINTS[url.pathname];
    } catch (error) {
      return false;
    }
  }

  if (window.fetch) {
    var originalFetch = window.fetch.bind(window);
    window.fetch = function (resource, init) {
      if (!isLocalActionEndpoint(resource)) {
        return originalFetch(resource, init);
      }
      var token = reportActionToken();
      if (!token) {
        return originalFetch(resource, init);
      }
      var options = init ? Object.assign({}, init) : {};
      var headers = new Headers(options.headers || (resource && resource.headers) || {});
      if (!headers.has(ACTION_TOKEN_HEADER)) {
        headers.set(ACTION_TOKEN_HEADER, token);
      }
      options.headers = headers;
      return originalFetch(resource, options);
    };
  }

  function norm(text) {
    return String(text || '').trim().toLowerCase();
  }

  function setCardMessage(card, message, isError) {
    var target = card ? card.querySelector('[data-ad-complete-message]') : null;
    if (!target) return;
    target.textContent = message || '';
    target.classList.toggle('status-error', !!isError);
  }

  function setCardDone(card) {
    if (!card) return;
    card.dataset.status = 'done';
    var status = card.querySelector('[data-ad-complete-status]');
    if (status) {
      status.textContent = '已执行';
      status.classList.remove('status-pending', 'status-watch', 'status-muted');
      status.classList.add('status-done');
    }
    var checkbox = card.querySelector('[data-ad-complete-checkbox]');
    if (checkbox) {
      checkbox.checked = true;
      checkbox.disabled = false;
    }
    setCardMessage(card, '已完成，取消勾选可撤销；点击上方重新生成报告后进入冷却和复盘。', false);
  }

  function setCardPending(card) {
    if (!card) return;
    card.dataset.status = 'pending';
    var status = card.querySelector('[data-ad-complete-status]');
    if (status) {
      status.textContent = '待确认';
      status.classList.remove('status-done', 'status-watch', 'status-muted');
      status.classList.add('status-pending');
    }
    var checkbox = card.querySelector('[data-ad-complete-checkbox]');
    if (checkbox) {
      checkbox.checked = false;
      checkbox.disabled = false;
    }
    delete card.dataset.adCompleteSavedPayload;
    setCardMessage(card, '已取消完成记录，点击上方重新生成报告后恢复待确认。', false);
  }

  function showRefreshControl(card) {
    var root = card ? card.closest('.ad-workbench') : document;
    var refresh = root ? root.querySelector('[data-ad-feedback-refresh]') : null;
    if (refresh) refresh.hidden = false;
  }

  function adCompletionErrorMessage(error) {
    var message = error && error.payload && error.payload.message ? error.payload.message : '';
    if (message === 'unknown endpoint') {
      return '本地确认服务版本过旧，请重新启动 start_report_action_server.command。';
    }
    return message || '本地确认服务未启动，请先启动 start_report_action_server.command。';
  }

  function submitAdCompletion(checkbox) {
    var card = checkbox.closest('[data-ad-complete-card]');
    if (!card) return;
    var payloadText = card.dataset.adCompletePayload || '';
    var payload = {};
    var payloads = [];
    try {
      payload = JSON.parse(payloadText);
      payloads = Array.isArray(payload) ? payload : [payload];
    } catch (error) {
      checkbox.checked = false;
      setCardMessage(card, '完成记录缺少必要数据，不能保存。', true);
      return;
    }
    if (!payloads.length) {
      checkbox.checked = false;
      setCardMessage(card, '完成记录缺少必要数据，不能保存。', true);
      return;
    }
    checkbox.disabled = true;
    setCardMessage(card, '正在写入完成记录...', false);
    fetch('http://127.0.0.1:8765/feedback/ad-action-complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payloads.length === 1 ? payloads[0] : { actions: payloads })
    })
      .then(function (response) {
        return response.json().then(function (result) {
          if (!response.ok || !result.ok) {
            var error = new Error(result.message || '保存失败');
            error.payload = result;
            throw error;
          }
          return result;
        });
      })
      .then(function (result) {
        var savedRows = result.feedbacks || (result.feedback ? [result.feedback] : payloads);
        card.dataset.adCompleteSavedPayload = JSON.stringify(savedRows);
        setCardDone(card);
        showRefreshControl(card);
      })
      .catch(function (error) {
        checkbox.disabled = false;
        checkbox.checked = false;
        setCardMessage(card, adCompletionErrorMessage(error), true);
      });
  }

  function submitAdCompletionCancel(checkbox) {
    var card = checkbox.closest('[data-ad-complete-card]');
    if (!card) return;
    var payloadText = card.dataset.adCompleteSavedPayload || card.dataset.adCompletePayload || '';
    var payload = {};
    var payloads = [];
    try {
      payload = JSON.parse(payloadText);
      payloads = Array.isArray(payload) ? payload : [payload];
    } catch (error) {
      setCardMessage(card, '取消记录缺少必要数据，不能撤销。', true);
      return;
    }
    if (!payloads.length) {
      setCardMessage(card, '取消记录缺少必要数据，不能撤销。', true);
      return;
    }
    checkbox.disabled = true;
    setCardMessage(card, '正在取消完成记录...', false);
    fetch('http://127.0.0.1:8765/feedback/ad-action-cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payloads.length === 1 ? payloads[0] : { actions: payloads })
    })
      .then(function (response) {
        return response.json().then(function (result) {
          if (!response.ok || !result.ok) {
            var error = new Error(result.message || '取消失败');
            error.payload = result;
            throw error;
          }
          return result;
        });
      })
      .then(function () {
        checkbox.disabled = false;
        setCardPending(card);
        showRefreshControl(card);
      })
      .catch(function (error) {
        checkbox.disabled = false;
        checkbox.checked = true;
        setCardMessage(card, adCompletionErrorMessage(error), true);
      });
  }

  document.addEventListener('change', function (event) {
    var checkbox = event.target.closest('[data-ad-complete-checkbox]');
    if (!checkbox) return;
    if (checkbox.checked) {
      submitAdCompletion(checkbox);
    } else {
      submitAdCompletionCancel(checkbox);
    }
  });
}());
"""

REPORT_UI_CSS += r"""
.ad-filter-summary {
  display: none;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: #eff6ff;
  color: #1e3a8a;
  font-weight: 800;
}
.ad-filter-summary.is-active {
  display: flex;
}
.ad-filter-hidden {
  display: none !important;
}
"""

REPORT_JS += r"""
(function () {
  function norm(value) {
    return String(value == null ? '' : value).trim().toLowerCase();
  }

  function actionKey(raw) {
    var text = norm(raw);
    if (!text) return '';
    if (text.indexOf('growth') >= 0 || text.indexOf('小预算') >= 0) return 'growth-test';
    if (text.indexOf('bid-up') >= 0 || text.indexOf('加价') >= 0 || text.indexOf('提高竞价') >= 0) return 'bid-up';
    if (text.indexOf('bid-down') >= 0 || text.indexOf('降竞价') >= 0) return 'bid-down';
    if (text.indexOf('negative') >= 0 || text.indexOf('否词') >= 0 || text.indexOf('否定') >= 0) return 'negative';
    if (text.indexOf('pause') >= 0 || text.indexOf('暂停') >= 0 || text.indexOf('关闭') >= 0) return 'pause';
    if (text.indexOf('create-exact') >= 0 || text.indexOf('拉精准') >= 0 || text.indexOf('新建精准') >= 0) return 'create-exact';
    if (text.indexOf('watch') >= 0 || text.indexOf('观察') >= 0) return 'watch';
    return text;
  }

  function itemStatus(item) {
    var status = norm(item.dataset.status);
    if (status) return status;
    var checkbox = item.querySelector('[data-ad-complete-checkbox]');
    if (checkbox && checkbox.checked) return 'done';
    return 'pending';
  }

  function itemAction(item) {
    return actionKey(item.dataset.action || item.dataset.actionLabel || item.getAttribute('data-action-label') || item.textContent || '');
  }

  function itemMarketplace(item) {
    return String(item.dataset.marketplace || '').trim().toUpperCase();
  }

  function itemSearchText(item) {
    return norm([
      item.dataset.searchText,
      item.dataset.searchTerm,
      item.dataset.actionLabel,
      item.dataset.marketplace,
      item.textContent
    ].join(' '));
  }

  function itemMatches(item, filters) {
    if (filters.query && itemSearchText(item).indexOf(filters.query) < 0) return false;
    if (filters.status !== 'all' && itemStatus(item) !== filters.status) return false;
    if (filters.action !== 'all' && itemAction(item) !== filters.action) return false;
    if (filters.marketplace !== 'all' && itemMarketplace(item) !== filters.marketplace) return false;
    return true;
  }

  function relevantItems(workbench) {
    return Array.prototype.slice.call(workbench.querySelectorAll('.ad-task-card, .ad-copy-box'));
  }

  function itemContainerVisible(section) {
    return !!section.querySelector('.ad-task-card:not(.ad-filter-hidden), .ad-copy-box:not(.ad-filter-hidden)');
  }

  function ensureFilterSummary(toolbar) {
    var existing = toolbar.parentElement.querySelector('.ad-filter-summary');
    if (existing) return existing;
    var summary = document.createElement('div');
    summary.className = 'ad-filter-summary';
    summary.setAttribute('data-ad-filter-summary', 'true');
    toolbar.insertAdjacentElement('afterend', summary);
    return summary;
  }

  function applyWorkbenchFilter(workbench) {
    var search = workbench.querySelector('[data-ad-search]');
    var status = workbench.querySelector('[data-ad-status]');
    var action = workbench.querySelector('[data-ad-action]');
    var marketplace = workbench.querySelector('[data-ad-marketplace]');
    var toolbar = workbench.querySelector('.ad-toolbar');
    if (!toolbar || !search || !status || !action) return;

    var filters = {
      query: norm(search.value),
      status: status.value || 'all',
      action: action.value || 'all',
      marketplace: marketplace ? (marketplace.value || 'all') : 'all'
    };
    var active = !!filters.query || filters.status !== 'all' || filters.action !== 'all' || filters.marketplace !== 'all';
    var summary = ensureFilterSummary(toolbar);
    var matched = 0;

    relevantItems(workbench).forEach(function (item) {
      var ok = !active || itemMatches(item, filters);
      item.classList.toggle('ad-filter-hidden', !ok);
      if (active && ok) matched += 1;
    });

    Array.prototype.slice.call(workbench.querySelectorAll('.ad-section')).forEach(function (section) {
      if (!active) {
        section.classList.remove('ad-filter-hidden');
        if (section.dataset.filterExpanded === 'true') {
          section.classList.add('is-collapsed');
          delete section.dataset.filterExpanded;
        }
        return;
      }
      var visible = itemContainerVisible(section);
      section.classList.toggle('ad-filter-hidden', !visible);
      if (visible && section.classList.contains('is-collapsed')) {
        section.classList.remove('is-collapsed');
        section.dataset.filterExpanded = 'true';
      }
    });

    summary.classList.toggle('is-active', active);
    summary.textContent = active ? (matched ? '筛选命中 ' + matched + ' 项' : '筛选无匹配项') : '';
  }

  function bindWorkbenchFilters() {
    Array.prototype.slice.call(document.querySelectorAll('.ad-workbench')).forEach(function (workbench) {
      if (workbench.dataset.adFilterBound === 'true') return;
      workbench.dataset.adFilterBound = 'true';
      ['input', 'change'].forEach(function (eventName) {
        workbench.addEventListener(eventName, function (event) {
          if (!event.target.closest('.ad-toolbar')) return;
          applyWorkbenchFilter(workbench);
        });
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindWorkbenchFilters);
  } else {
    bindWorkbenchFilters();
  }
}());
"""

REPORT_JS += r"""
(function () {
  function attachCompletionRows() {
    document.querySelectorAll('[data-ad-complete-card]').forEach(function (card) {
      var row = card.querySelector('.ad-complete-row');
      var message = card.querySelector('[data-ad-complete-message]');
      if (!row || !message || row.contains(message)) return;
      if (message.tagName === 'DIV') {
        var span = document.createElement('span');
        span.className = message.className || 'subtle';
        span.dataset.adCompleteMessage = '';
        span.textContent = message.textContent || '';
        message.remove();
        row.appendChild(span);
      } else {
        row.appendChild(message);
      }
    });
  }

  function completionRowHtml() {
    return '<div class="ad-complete-row"><label class="ad-complete-control"><input type="checkbox" data-ad-complete-checkbox><span>标记已完成</span></label><span class="subtle" data-ad-complete-message></span></div>';
  }

  function normalizeText(text) {
    return String(text || '').trim().toLowerCase();
  }

  function readPayloads(card) {
    try {
      var parsed = JSON.parse(card.dataset.adCompletePayload || '[]');
      return Array.isArray(parsed) ? parsed : [parsed];
    } catch (error) {
      return [];
    }
  }

  function compactCopyWorkbench() {
    var cards = Array.prototype.slice.call(document.querySelectorAll('.ad-task-card[data-ad-complete-payload]'));
    document.querySelectorAll('.ad-copy-box').forEach(function (box) {
      if (box.dataset.adCompletePayload) return;
      var marketplace = normalizeText(box.dataset.marketplace);
      var actionLabel = normalizeText(box.dataset.actionLabel);
      var payloads = [];
      cards.forEach(function (card) {
        if (normalizeText(card.dataset.marketplace) !== marketplace) return;
        if (actionLabel && normalizeText(card.dataset.actionLabel) !== actionLabel) return;
        payloads = payloads.concat(readPayloads(card));
      });
      payloads = payloads.filter(Boolean);
      if (!payloads.length) return;
      box.dataset.adCompleteCard = 'true';
      box.dataset.adCompletePayload = JSON.stringify(payloads.length === 1 ? payloads[0] : payloads);
      box.dataset.actionId = String(payloads[0].action_id || '');
      box.dataset.searchTerm = String(payloads[0].search_term_or_target || '');
      box.dataset.actionLabel = String(payloads[0].manual_action_taken || payloads[0].suggested_action || box.dataset.actionLabel || '');
      if (!box.querySelector('.ad-complete-row')) {
        box.insertAdjacentHTML('beforeend', completionRowHtml());
      }
    });
    document.querySelectorAll('.ad-workbench > .ad-section').forEach(function (section) {
      var title = section.querySelector('.ad-section-header h3');
      var text = title ? title.textContent.trim() : '';
      if (text === '今日待处理') {
        section.classList.add('is-copy-only-hidden');
      }
    });
    var growth = document.getElementById('growth-test-actions');
    if (growth) {
      growth.querySelectorAll(':scope > .ad-task-grid').forEach(function (grid) {
        grid.classList.add('is-copy-only-hidden');
      });
    }
    attachCompletionRows();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      attachCompletionRows();
      compactCopyWorkbench();
    });
  } else {
    attachCompletionRows();
    compactCopyWorkbench();
  }
}());
"""

REPORT_JS += r"""
(function () {
  function copyButtonText(button, label) {
    var old = button.dataset.copyOriginalLabel || button.textContent || '复制';
    button.dataset.copyOriginalLabel = old;
    button.textContent = label;
    button.classList.add('copied');
    clearTimeout(button._copyResetTimer);
    button._copyResetTimer = setTimeout(function () {
      button.textContent = old;
      button.classList.remove('copied');
    }, 1800);
  }

  function selectTargetText(target) {
    if (!target) return;
    var range = document.createRange();
    range.selectNodeContents(target);
    var selection = window.getSelection();
    if (!selection) return;
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function legacyTextareaCopy(text) {
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'readonly');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    var copied = false;
    try {
      copied = !!(document.execCommand && document.execCommand('copy'));
    } catch (error) {
      copied = false;
    }
    textarea.remove();
    return copied;
  }

  function fallbackCopy(button, target, text) {
    if (legacyTextareaCopy(text)) {
      copyButtonText(button, '已复制');
      return;
    }
    selectTargetText(target);
    copyButtonText(button, '按Cmd+C复制');
  }

  function localServiceCopy(text) {
    if (!window.fetch) return Promise.reject(new Error('fetch unavailable'));
    return fetch('http://127.0.0.1:8765/copy/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok || !payload.ok) {
          throw new Error(payload.message || 'local copy failed');
        }
        return payload;
      });
    });
  }

  document.addEventListener('click', function (event) {
    var copyButton = event.target.closest('[data-copy-target]');
    if (!copyButton) return;
    var target = document.getElementById(copyButton.dataset.copyTarget);
    var text = target ? (target.innerText || target.textContent || '') : '';
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!text.trim()) {
      copyButtonText(copyButton, '无内容');
      return;
    }
    localServiceCopy(text).then(function () {
      copyButtonText(copyButton, '已复制');
    }).catch(function () {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () {
          copyButtonText(copyButton, '已复制');
        }).catch(function () {
          fallbackCopy(copyButton, target, text);
        });
      } else {
        fallbackCopy(copyButton, target, text);
      }
    });
  }, true);
}());
"""

REPORT_JS += r"""
(function () {
  function injectCompletionLayoutFix() {
    if (document.getElementById('ad-copy-completion-layout-fix')) return;
    var style = document.createElement('style');
    style.id = 'ad-copy-completion-layout-fix';
    style.textContent = [
      '.ad-copy-box{position:relative;display:flex;flex-direction:column;gap:8px;padding-bottom:10px;}',
      '.ad-copy-box .ad-complete-row{position:static;display:flex;align-items:center;gap:10px;min-height:22px;margin:0;padding:0 2px;}',
      '.ad-copy-box .ad-complete-control{display:inline-flex;align-items:center;gap:5px;min-width:0;line-height:1.2;font-size:13px;font-weight:700;color:#334155;white-space:nowrap;}',
      '.ad-copy-box .ad-complete-control input[type="checkbox"]{width:14px;height:14px;flex:0 0 auto;margin:0;}',
      '.ad-copy-box [data-ad-complete-message]{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
    ].join('\n');
    document.head.appendChild(style);
  }

  function safeText(value) {
    return String(value == null ? '' : value);
  }

  function growthEvidenceDisplay(value) {
    var text = safeText(value).trim();
    var labels = {
      '历史广告订单': '曾有广告单',
      '核心强相关': '主词相关',
      '强意图长尾': '长尾相关',
      '有点击样本不足': '有点击待验证'
    };
    return labels[text] || text;
  }

  function trafficOriginDisplay(item) {
    if (item && item.traffic_origin) return safeText(item.traffic_origin) || '未识别';
    var matchText = [
      item && item.match_type,
      item && item.match_type_or_targeting,
      item && item.matched_target,
      item && item.targeting
    ].map(safeText).join(' ').toLowerCase();
    if (/(auto|close-match|loose-match|substitutes|complements|close match|loose match)/.test(matchText)) return '自动广告';
    if (/(exact|phrase|broad|精准|词组|广泛)/.test(matchText)) return '手动广告';
    var term = safeText((item && (item.search_term_or_target || item.search_term || item.targeting)) || '').trim();
    var targetingText = [
      item && item.targeting,
      item && item.match_type_or_targeting
    ].map(safeText).join(' ').toLowerCase();
    if (/^B0[A-Z0-9]{8,}$/i.test(term) || /(asin定向|asin 定向|product targeting|product-targeting|商品投放|商品定向)/.test(targetingText)) return 'ASIN定向';
    var campaignText = [
      item && item.campaign_name,
      item && item.campaign
    ].map(safeText).join(' ').toLowerCase();
    if (/(自动|auto)/.test(campaignText)) return '自动广告';
    if (/(手动|manual|精准|exact|词组|phrase|广泛|broad)/.test(campaignText)) return '手动广告';
    var reviewText = [
      item && item.confirmed_note,
      item && item.manual_action_taken,
      item && item.action_detail,
      item && item.normalized_action
    ].map(safeText).join(' ').toLowerCase();
    if (/(自动出单词|自动广告|auto)/.test(reviewText)) return '自动广告';
    if (reviewText.indexOf('泛核心词') >= 0 && reviewText.indexOf('降竞价') >= 0) return '手动广告';
    if (reviewText.indexOf('bid_down') >= 0 && /(核心词|泛核心)/.test(reviewText)) return '手动广告';
    return '未识别';
  }

  function growthMatchText(item) {
    return [
      item && item.match_type,
      item && item.match_type_or_targeting,
      item && item.targeting,
      item && item.matched_target
    ].map(safeText).join(' ').toLowerCase();
  }

  function isExistingExactGrowth(item) {
    var matchText = growthMatchText(item);
    if (!/(exact|精准)/.test(matchText)) return false;
    if (/(targeting_expression_predefined|close-match|loose-match|substitutes|complements)/.test(matchText)) return false;
    return trafficOriginDisplay(item) === '手动广告';
  }

  function operationLabelDisplay(item) {
    if (item && item.operation_label) return safeText(item.operation_label) || '拉精准';
    if (isExistingExactGrowth(item)) return '已在精准，管理原广告';
    var origin = trafficOriginDisplay(item);
    var matchText = growthMatchText(item);
    if (origin === '自动广告') return '自动出词，拉精准';
    if (matchText.indexOf('phrase') >= 0 || matchText.indexOf('词组') >= 0) return '词组出词，拉精准';
    if (matchText.indexOf('broad') >= 0 || matchText.indexOf('广泛') >= 0) return '广泛出词，拉精准';
    if (origin === 'ASIN定向') return 'ASIN定向，单独评估';
    if (origin === '手动广告') return '手动出词，拉精准';
    return '来源待核对，暂不盲开';
  }

  function growthCopyLine(item) {
    return safeText(item.search_term_or_target || 'N/A');
  }

  function createEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = text;
    return el;
  }

  function ensureGrowthCopyBoxes() {
    var section = document.getElementById('growth-test-actions');
    if (!section || section.querySelector('.growth-copy-box')) return;
    var cards = Array.prototype.slice.call(section.querySelectorAll('[data-ad-complete-payload]'));
    var groups = [];
    cards.forEach(function (card) {
      var payloads = [];
      try {
        var parsed = JSON.parse(card.dataset.adCompletePayload || '[]');
        payloads = Array.isArray(parsed) ? parsed : [parsed];
      } catch (error) {
        payloads = [];
      }
      payloads = payloads.filter(function (item) {
        return item && String(item.normalized_action || item.suggested_action || '').indexOf('growth') >= 0 || item && String(item.suggested_action || '').indexOf('小预算') >= 0;
      });
      payloads.forEach(function (item) {
        if (item && !item.traffic_origin) item.traffic_origin = trafficOriginDisplay(item);
        if (item && !item.operation_label) item.operation_label = operationLabelDisplay(item);
      });
      if (payloads.length) groups.push({ card: card, payloads: payloads });
    });
    if (!groups.length) return;
    var wrapper = createEl('div', 'ad-action-group growth-copy-group');
    groups.forEach(function (group, index) {
      var first = group.payloads[0] || {};
      var blockId = 'growth-test-dynamic-copy-' + (index + 1);
      var marketplace = safeText(first.marketplace || group.card.dataset.marketplace || 'N/A').toUpperCase();
      var box = createEl('div', 'ad-copy-box growth-copy-box');
      box.dataset.copyGroup = blockId;
      box.dataset.marketplace = marketplace;
      box.dataset.actionLabel = '小预算试投';
      box.dataset.adCompleteCard = 'true';
      box.dataset.adCompletePayload = JSON.stringify(group.payloads);
      box.dataset.actionId = String(first.action_id || '');
      box.dataset.searchTerm = String(first.search_term_or_target || '');

      var head = createEl('div', 'ad-copy-head');
      var title = createEl('div', 'ad-copy-title');
      var market = createEl('span', 'status-badge status-muted ad-copy-market', marketplace);
      var totalBudget = group.payloads.reduce(function (sum, item) {
        var value = parseFloat(String(item.suggested_daily_budget || '').replace(/[^0-9.]/g, ''));
        return sum + (isNaN(value) ? 0 : value);
      }, 0);
      var firstBudget = safeText(first.suggested_daily_budget || '');
      var symbol = firstBudget.charAt(0).match(/[$£€]/) ? firstBudget.charAt(0) : '';
      var budgetText = totalBudget ? '总预算 ' + symbol + totalBudget.toFixed(2) + '/天' : '';
      var strong = createEl('strong', '', safeText(first.product_name || '小预算试投'));
      var meta = createEl('span', 'subtle', [marketplace, first.product_name, first.sku, first.asin, budgetText].filter(Boolean).join(' '));
      title.appendChild(market);
      title.appendChild(strong);
      title.appendChild(meta);
      var button = createEl('button', 'copy-button', '复制');
      button.type = 'button';
      button.dataset.copyTarget = blockId;
      head.appendChild(title);
      head.appendChild(button);
      box.appendChild(head);

      var visual = createEl('div', 'ad-copy-visual');
      group.payloads.forEach(function (item) {
        var row = createEl('div', 'ad-copy-row');
        row.dataset.adCopyRow = 'true';
        row.dataset.marketplace = marketplace;
        row.dataset.actionLabel = '小预算试投';
        row.dataset.searchTerm = safeText(item.search_term_or_target || 'N/A');
        row.appendChild(createEl('div', 'ad-copy-target', safeText(item.search_term_or_target || 'N/A')));
        var context = createEl('div', 'ad-copy-context');
        var chips = [
          '站点 ' + marketplace,
          '来源 ' + trafficOriginDisplay(item),
          '操作 ' + operationLabelDisplay(item),
          '竞价 ' + safeText(item.suggested_bid_min || 'N/A') + '-' + safeText(item.suggested_bid_max || 'N/A'),
          '依据 ' + safeText(growthEvidenceDisplay(item.evidence_level) || '待验证')
        ];
        var matchLabel = safeText(item.match_type || item.match_type_or_targeting || '').trim();
        if (matchLabel) chips.splice(3, 0, '匹配 ' + matchLabel);
        chips.forEach(function (text) {
          context.appendChild(createEl('span', '', text));
        });
        row.appendChild(context);
        visual.appendChild(row);
      });
      box.appendChild(visual);

      var pre = createEl('pre', 'ad-copy-text copy-source');
      pre.id = blockId;
      pre.textContent = group.payloads.map(growthCopyLine).join('\n');
      box.appendChild(pre);
      box.insertAdjacentHTML('beforeend', '<div class="ad-complete-row"><label class="ad-complete-control"><input type="checkbox" data-ad-complete-checkbox><span>标记已完成</span></label><span class="subtle" data-ad-complete-message></span></div>');
      wrapper.appendChild(box);
    });
    var grid = section.querySelector('.ad-task-grid');
    section.insertBefore(wrapper, grid || null);
    Array.prototype.slice.call(section.children).forEach(function (child) {
      if (child.classList && child.classList.contains('ad-task-grid')) {
        child.classList.add('is-copy-only-hidden');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      injectCompletionLayoutFix();
      ensureGrowthCopyBoxes();
    });
  } else {
    injectCompletionLayoutFix();
    ensureGrowthCopyBoxes();
  }
}());
"""
