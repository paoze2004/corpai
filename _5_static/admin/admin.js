// Phase 3 Admin UI shared helper — fetch Bearer 自动注入 + 401 跳登录

const apiFetch = async (path, options = {}) => {
    const token = localStorage.getItem('admin_token');
    const opts = {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            ...(options.headers || {}),
        },
    };
    const r = await fetch(`/admin/api${path}`, opts);
    if (r.status === 401) {
        localStorage.removeItem('admin_token');
        if (!path.startsWith('/login')) {
            window.location.href = 'login.html';
            return Promise.reject(new Error('unauthorized'));
        }
    }
    if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
            const body = await r.json();
            msg = body.detail || JSON.stringify(body);
        } catch (e) { /* ignore */ }
        throw new Error(msg);
    }
    const ct = r.headers.get('content-type') || '';
    return ct.includes('application/json') ? r.json() : r.text();
};

const logout = () => {
    localStorage.removeItem('admin_token');
    localStorage.removeItem('admin_role');
    window.location.href = 'login.html';
};

const fmtTime = (ts) => {
    if (!ts) return '';
    try {
        const d = new Date(ts);
        return d.toLocaleString('zh-CN');
    } catch (e) { return String(ts); }
};

const renderTable = (rows, columns) => {
    if (!rows || rows.length === 0) return '<p class="muted">无数据</p>';
    const thead = '<tr>' + columns.map(c => `<th>${c.title}</th>`).join('') + '</tr>';
    const tbody = rows.map(r => '<tr>' + columns.map(c => {
        const v = c.render ? c.render(r) : (r[c.key] ?? '');
        return `<td>${v}</td>`;
    }).join('') + '</tr>').join('');
    return `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
};

const paginated = (data) => `
    <div class="row-flex">
        <span class="muted">共 ${data.total} 条, 第 ${data.page} 页, 每页 ${data.size} 条</span>
    </div>
`;
