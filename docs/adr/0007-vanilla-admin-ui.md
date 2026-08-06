# ADR-007: 管理后台保持 Vanilla JS,不引入框架

## 状态
**Accepted** — 2026-08-06

## 背景

管理后台是 Phase 3 的核心交付物之一。需要支持:
- 插件注册/启停/查看(agents 页)
- MCP 工具列表/启停(tools 页)
- 用户管理 + 角色分配(users 页)
- 调用日志查询 + 筛选(logs 页)
- 简单指标图表(metrics 页)

### 当前前端能力
`CorpAI/static/index.html`(485 行)是**单文件 vanilla SPA**:
- 无构建步骤(FastAPI 直接静态文件 serve)
- 无依赖(无 npm/node_modules)
- 无框架(无 React/Vue/Svelte)
- 实现了:聊天窗口、Agent cards 展示、记忆查看/编辑/清空、用户偏好 CRUD

**结论**:团队已经证明能 ship 485 行 vanilla SPA,且功能完整。

### 风险点
1. **Scope creep**:管理后台容易越加越多(图表/钻取/自定义 dashboard/RBAC 矩阵编辑器)
2. **学习曲线**:若新开发者不熟 vanilla JS,需要适配
3. **复杂度天花板**:vanilla SPA 到 1500-2000 LOC 后,DOM 操作会变痛苦

## 决策

**管理后台保持 Vanilla JS,不引入 React/Vue**。

### MVP 范围(5 页,严格限制)

```
static/admin/
├── index.html         # 入口,带左侧导航 + iframe 加载子页(或 router)
├── agents.html        # 插件列表/详情/启停
├── tools.html         # MCP 工具列表
├── users.html         # 用户列表/角色编辑
├── logs.html          # 调用日志(分页 + 时间筛选)
└── metrics.html       # /metrics 简单展示
```

**每页限制**:
- 列表(表格 + 分页)
- 创建(简单表单)
- 编辑(同表单)
- 删除(确认弹窗)
- **不做**:图表钻取、RBAC 矩阵编辑器、自定义 dashboard、富文本编辑

### 技术约束

- **无构建步骤**:纯 HTML + `<script>` + `<style>`,FastAPI `StaticFiles` 直接 serve
- **CSS 沿用**:复用 `static/index.html` 的 dark theme 调色板(`#1a1a2e` / `#16213e` / `#e94560`)
- **JS 工具库**:可选 `fetch` 包装 + DOM helpers;不引 jQuery/Alpine
- **API 调用**:用 `fetch()` 直接调 `/admin/api/*` 端点

### API 端点(MVP)

```
GET    /admin/api/agents           # 列出所有插件
POST   /admin/api/agents/{name}/enable
POST   /admin/api/agents/{name}/disable
GET    /admin/api/tools
GET    /admin/api/users
POST   /admin/api/users/{id}/role
GET    /admin/api/logs?page=1&size=20&user_id=&from=&to=
GET    /admin/api/metrics           # /metrics proxy(加 RBAC)
```

### 升级阈值(明确规则)

**当且仅当**以下条件之一满足,才考虑升级:

| 条件 | 阈值 | 升级方案 |
|------|------|---------|
| 总 LOC | > 1500 | 升级到 **HTMX**(无构建 + 服务端渲染片段) |
| 交互复杂 | > 5 个状态联动 + 表单依赖 | HTMX + Alpine.js |
| 团队规模 | > 3 个前端开发者 | React + Vite + 拆分 admin bundle |

**未达到阈值前,严禁引入框架**。

### HTMX 备选方案
如果升级触发:
```html
<!-- HTMX 风格 -->
<button hx-post="/admin/api/users/123/role"
        hx-vals='{"role": "admin"}'
        hx-swap="outerHTML">
  升级为 admin
</button>
```
- 服务端返回 HTML 片段,客户端无 JS 框架
- 仍无构建步骤
- 适合"按钮触发片段刷新"场景

### React/Vite 备选方案(更激进)
只有当 HTMX 也不够用时才考虑:
- 引入 `node_modules`
- 引入 `vite build` 步骤
- 拆分 `static/user/` 和 `static/admin/` 两个 bundle
- 预计 +1.5 周工作量

## 后果

### 正面
1. **零依赖启动**:无 npm install / 无 node_modules / 无 vite build
2. **快速迭代**:改 HTML 直接刷新,无热重载配置
3. **代码量小**:MVP 5 页预计总共 ~1200 LOC(含所有 CRUD)
4. **沿用现有风格**:`static/index.html` 的设计系统可复用
5. **避免构建错误**:无 webpack/vite 配置错误阻塞

### 负面
1. **Scope 严格**:不能加图表/钻取/自定义,可能让 admin 用户失望
2. **DOM 操作繁琐**:复杂表格(>100 行)需要手写分页逻辑
3. **可访问性**:vanilla JS 容易忽略 ARIA、键盘导航
4. **测试困难**:无组件测试框架,只能手测

### 中性
1. **未来可能升级**:HTMX 在 1500 LOC 阈值;React 在 3000 LOC 阈值
2. **复用现有 static 目录**:与用户聊天窗口同目录,共用 nginx 配置

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **React + Vite + TypeScript** | ❌ 拒绝 — 当前 485 行 vanilla SPA 证明不需要;引入构建链和依赖增加复杂度 |
| **Vue 3 + Composition API** | ❌ 拒绝 — 同上,只是不同的框架;vanilla 更轻 |
| **HTMX** | ⚠️ 备选 — 升级阈值触发时再用;当前 vanilla 足够 |
| **Alpine.js**(轻量指令式) | ⚠️ 备选 — 比 vanilla 强一点,但仍无构建;MVP 不需要 |
| **Tailwind CSS** | ❌ 拒绝 — 当前项目无 CSS 框架;vanilla CSS 沿用调色板即可 |

## 验证

- **Phase 3 验收**:`static/admin/*.html` 5 页全部可点
- **Phase 3 验收**:`grep -E "react|vue|angular" static/admin/` 返回空(无框架依赖)
- **Phase 3 验收**:admin 用户登录 → 看到所有 5 页;employee 用户登录 → 重定向到 403
- **Phase 5 验收**:管理后台能 CRUD 4 个示范插件

## 参考引用

- 现有 SPA 模板:`CorpAI/static/index.html:1-485`
- Dark theme 调色板:`CorpAI/static/index.html:7-15`
- FastAPI 静态文件:`CorpAI/api/app.py:40-49`
