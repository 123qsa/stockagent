// 股票公告分析师 - 前端逻辑

const state = {
    stocks: [],
    announcements: [],
    selectedStock: null,
    selectedAnnouncement: null,
    analysisType: 'summary',
    messages: [], // {role: 'user'|'assistant', content: string, metadata: {}}
    isLoading: false,
};

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', () => {
    loadStocks();
    setupMarked();
});

function setupMarked() {
    marked.setOptions({
        highlight: function(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, {language: lang}).value;
            }
            return hljs.highlightAuto(code).value;
        },
        breaks: true,
        gfm: true,
    });
}

// ========== 股票列表 ==========
async function loadStocks() {
    try {
        const resp = await fetch('/api/stocks');
        state.stocks = await resp.json();
        renderStockList(state.stocks);
    } catch (e) {
        console.error('加载股票失败:', e);
        showError('加载股票列表失败');
    }
}

function renderStockList(stocks) {
    const container = document.getElementById('stockList');
    container.innerHTML = stocks.map(s => `
        <div class="stock-item ${state.selectedStock?.code === s.code ? 'active' : ''}"
             onclick="selectStock('${s.code}')"
             data-code="${s.code}" data-name="${s.name || ''}">
            <span class="stock-code">${s.code}</span>
            <span class="stock-name">${s.name || ''}</span>
            <span class="stock-market">${s.market || ''}</span>
        </div>
    `).join('');
}

function filterStocks() {
    const keyword = document.getElementById('stockSearch').value.trim().toLowerCase();
    const filtered = state.stocks.filter(s =>
        (s.code && s.code.toLowerCase().includes(keyword)) ||
        (s.name && s.name.toLowerCase().includes(keyword))
    );
    renderStockList(filtered);
}

async function selectStock(code) {
    state.selectedStock = state.stocks.find(s => s.code === code);
    state.selectedAnnouncement = null;
    state.messages = []; // 切换股票时清空对话

    // 更新UI
    renderStockList(state.stocks);
    updateHeader();
    renderMessages();

    // 加载公告
    const section = document.getElementById('announcementSection');
    section.style.display = 'flex';
    document.getElementById('selectedStockName').textContent =
        `${state.selectedStock.code} ${state.selectedStock.name || ''}`;

    try {
        const resp = await fetch(`/api/stocks/${code}/announcements?limit=50`);
        state.announcements = await resp.json();
        renderAnnouncementList();
    } catch (e) {
        console.error('加载公告失败:', e);
        showError('加载公告列表失败');
    }
}

function closeAnnouncementSection() {
    document.getElementById('announcementSection').style.display = 'none';
}

// ========== 公告列表 ==========
function renderAnnouncementList() {
    const container = document.getElementById('announcementList');
    if (!state.announcements.length) {
        container.innerHTML = '<div style="padding:20px;color:var(--text-secondary);text-align:center;">暂无公告</div>';
        return;
    }

    container.innerHTML = state.announcements.map(a => `
        <div class="ann-item ${state.selectedAnnouncement?.id === a.id ? 'active' : ''} ${a.parsed ? 'parsed' : ''}"
             onclick="selectAnnouncement('${a.id}', '${escapeHtml(a.title)}')">
            <div class="ann-title">${escapeHtml(a.title)}</div>
            <div class="ann-meta">
                <span>${a.time || ''}</span>
                <span class="ann-status">${a.parsed ? '✓ 已解析' : (a.downloaded ? '已下载' : '未下载')}</span>
            </div>
        </div>
    `).join('');
}

function selectAnnouncement(id, title) {
    state.selectedAnnouncement = { id, title };
    renderAnnouncementList();
    updateHeader();
    updateInputContext();
}

function updateHeader() {
    const stockEl = document.getElementById('headerStock');
    const annEl = document.getElementById('headerAnn');

    if (state.selectedStock) {
        stockEl.textContent = `${state.selectedStock.code} ${state.selectedStock.name || ''}`;
    } else {
        stockEl.textContent = '未选择股票';
    }

    if (state.selectedAnnouncement) {
        annEl.textContent = state.selectedAnnouncement.title;
    } else {
        annEl.textContent = '';
    }
}

function updateInputContext() {
    const el = document.getElementById('inputContext');
    if (state.selectedAnnouncement) {
        el.textContent = `当前上下文: ${state.selectedAnnouncement.title.substring(0, 40)}${state.selectedAnnouncement.title.length > 40 ? '...' : ''}`;
    } else if (state.selectedStock) {
        el.textContent = `当前股票: ${state.selectedStock.code}（未选择公告，将基于通用知识回答）`;
    } else {
        el.textContent = '';
    }
}

// ========== 分析类型 ==========
function onAnalysisTypeChange() {
    state.analysisType = document.getElementById('analysisType').value;
}

// ========== 对话 ==========
function startNewChat() {
    state.messages = [];
    state.selectedAnnouncement = null;
    renderMessages();
    updateHeader();
    updateInputContext();
    renderAnnouncementList();
}

function quickAsk(text) {
    if (!state.selectedStock) {
        showError('请先选择一只股票');
        return;
    }
    document.getElementById('messageInput').value = text;
    autoResize(document.getElementById('messageInput'));
    sendMessage();
}

function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

async function sendMessage() {
    const input = document.getElementById('messageInput');
    const text = input.value.trim();
    if (!text || state.isLoading) return;

    if (!state.selectedStock) {
        showError('请先选择一只股票');
        return;
    }

    // 添加用户消息
    addMessage('user', text);
    input.value = '';
    input.style.height = 'auto';

    // 显示加载
    state.isLoading = true;
    document.getElementById('sendBtn').disabled = true;
    document.getElementById('loadingOverlay').style.display = 'flex';

    try {
        const resp = await fetch('/api/chat/v2', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                stock_code: state.selectedStock.code,
                announcement_id: state.selectedAnnouncement?.id || '',
                analysis_type: state.analysisType,
                history: state.messages.filter(m => m.role !== 'system').slice(-12),
            }),
        });

        const data = await resp.json();

        if (data.error) {
            addMessage('assistant', `❌ 错误: ${data.error}`, { error: true });
        } else {
            addMessage('assistant', data.content, {
                tokens: data.tokens,
                analysis_type: data.analysis_type,
                analysis_name: data.analysis_name,
            });
        }
    } catch (e) {
        console.error('发送消息失败:', e);
        addMessage('assistant', `❌ 请求失败: ${e.message}`, { error: true });
    } finally {
        state.isLoading = false;
        document.getElementById('sendBtn').disabled = false;
        document.getElementById('loadingOverlay').style.display = 'none';
    }
}

function addMessage(role, content, metadata = {}) {
    state.messages.push({ role, content, metadata });
    renderMessages();
}

function renderMessages() {
    const container = document.getElementById('messagesArea');

    if (!state.messages.length) {
        container.innerHTML = `
            <div class="welcome-screen" id="welcomeScreen">
                <div class="welcome-content">
                    <h1>股票公告智能分析</h1>
                    <p>选择左侧股票和公告，开始与 AI 分析师对话</p>
                    <div class="quick-actions">
                        <div class="quick-card" onclick="quickAsk('这份公告的核心内容是什么？')">
                            <span>📋</span> 摘要这份公告
                        </div>
                        <div class="quick-card" onclick="quickAsk('这份公告对股价有什么影响？')">
                            <span>📈</span> 分析股价影响
                        </div>
                        <div class="quick-card" onclick="quickAsk('公告中提到了哪些关键财务数据？')">
                            <span>💰</span> 提取财务数据
                        </div>
                        <div class="quick-card" onclick="quickAsk('这份公告有哪些潜在风险？')">
                            <span>⚠️</span> 识别风险点
                        </div>
                    </div>
                </div>
            </div>
        `;
        return;
    }

    container.innerHTML = state.messages.map((m, i) => {
        const isUser = m.role === 'user';
        const avatar = isUser ? '👤' : '🤖';
        const htmlContent = isUser ? escapeHtml(m.content) : marked.parse(m.content);

        let metaHtml = '';
        if (m.metadata?.tokens) {
            metaHtml += `<span style="color:var(--text-secondary);font-size:12px;margin-left:8px;">(${m.metadata.tokens} tokens)</span>`;
        }
        if (m.metadata?.analysis_name) {
            metaHtml += `<span style="color:var(--accent-color);font-size:12px;margin-left:8px;">[${m.metadata.analysis_name}]</span>`;
        }

        return `
            <div class="message ${m.role}">
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <div>${htmlContent}</div>
                    ${metaHtml}
                </div>
            </div>
        `;
    }).join('');

    // 代码高亮
    container.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });

    // 滚动到底部
    container.scrollTop = container.scrollHeight;
}

// ========== 侧边栏切换 ==========
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('collapsed');
}

// ========== 工具函数 ==========
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showError(msg) {
    // 简单实现：用 alert，后续可改为 toast
    alert(msg);
}
