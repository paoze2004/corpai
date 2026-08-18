# LAYERS — 项目分层与编号约定

> 把所有 `_0_` / `_1_` / `_2_` 等编号约定一次性写死,避免下次又有人问"为啥这么命名"。

---

## 顶层 6 个目录(0-5)

```
_0_CorpAI/        ← Python 平台包(应用项目,不打包到 site-packages)
_1_plugins/       ← 业务能力包(各为独立 pip 包,本地 editable 安装)
_2_scripts/       ← 运维脚本(bootstrap / migrate / 启动)
_3_sql/           ← SQL DDL + 迁移
_4_tests/         ← 测试
_5_static/        ← Web 静态资源(HTML/CSS/JS,跟 Python 代码解耦)
logs/             ← 运行时产物(不编号 — 不进版本控制)
```

| 编号 | 目录 | 内容 |
|---|---|---|
| **0** | `_0_CorpAI/` | Python 平台包:业务运行时 |
| **1** | `_1_plugins/` | 3 个能力包(hr_assistant / sre_copilot / knowledge) |
| **2** | `_2_scripts/` | bootstrap users / migrate / demo runner |
| **3** | `_3_sql/` | create_all_tables.sql + 各 phase DDL |
| **4** | `_4_tests/` | pytest(unit + integration marker) |
| **5** | `_5_static/` | Admin Web 静态资源 |

### 编号原则

- **数字 = 依赖顺序**:平台(0)不依赖插件(1),插件被平台加载;脚本(2)操作平台和 DB(3);测试(4)反过来验证(0/1/2/3);静态资源(5)完全独立
- **IDE 排序友好**:打开目录按数字排,新人一眼看出"平台 → 插件 → 脚本 → DB → 测试 → 静态"的依赖图
- **新增同类项目无歧义**:未来加 `_6_docs/` `_7_deploy/` 不会冲突

### 为什么不加更多编号

- 数字无意义时**不编号**:`logs/` 不进版本控制,加 `_6_logs/` 没价值
- 数字只能加 1 个量级(目前到 5,再大就该按子目录分了,不是同一层级)

---

## `_0_CorpAI/` 内部 4 层(0-3)

```
_0_CorpAI/
├── _0_api/          ← 入站适配(FastAPI 边界)
├── _1_core/         ← 业务核心(纯算法,框架无关)
├── _2_platform/     ← 基础设施 + 横切关注点
│   ├── orchestrator/
│   ├── auth/
│   ├── observability/
│   ├── db.py
│   ├── plugin_manager.py
│   └── wiring.py    ← ★ Composition Root
└── _3_utils/        ← 工具
```

| 编号 | 目录 | 职责 |
|---|---|---|
| **0** | `_0_api/` | FastAPI app + routers,唯一接触 HTTP 的层 |
| **1** | `_1_core/` | 业务实体(`ConversationMemory` / prompts),纯 Python,无框架依赖 |
| **2** | `_2_platform/` | orchestrator / auth / observability / db / plugin_manager / **wiring.py** |
| **3** | `_3_utils/` | dotenv / format / strip_think 等小工具 |

### 依赖规则(重要!)

```
_0_api  ─┬─→  _2_platform  ─→  _3_utils
         │
         └─────────────────────→  _3_utils
_1_core  ←───(无依赖)──────────
```

- ✅ `_0_api` 可以 import `_2_platform` 和 `_3_utils`
- ✅ `_2_platform` 可以 import `_1_core` 和 `_3_utils`
- ❌ **`_1_core` 不可以 import 任何框架**(FastAPI / LangChain / mysql)
- ❌ **`_2_platform/wiring.py` 是 Composition Root**——是**唯一**允许 import LangChain / python_a2a / mysql.connector 的地方

---

## 命名规则:Python 包名 vs Distribution 名

| 维度 | 规则 | 例子 |
|---|---|---|
| **Python 包名**(`import x.y`) | PEP 8:可字母/下划线开头,**不能数字开头** | ✅ `import _0_CorpAI._0_api.app` |
| **Distribution 名**(`pip install <name>`) | PEP 503:必须字母数字开头/结尾,中间可含 `.` `_` `-` | ✅ `name = "corpai-plugin-knowledge"` |

**我们的 distribution 名**:`corpai-plugin-hr-assistant` / `corpai-plugin-sre-copilot` / `corpai-plugin-knowledge` —— **字母开头,完全合规**。

**我们的目录前缀**:`_0_` / `_1_` / `_2_` / `_3_` / `_4_` / `_5_` —— **下划线开头,这是合法的 Python 标识符**,但**不是**合法的 distribution name。所以**别**把目录名当 pip install 的目标。

---

## 为什么不放更多项目在同一层

- **plugin 是能力包,不是层**:`_1_plugins/hr_assistant/` 是一个完整的业务能力,内部有自己的 `src/` / `hr_tests/` / `pyproject.toml`,是独立可分发的 Python 包。它跟 `_0_CorpAI/api` 不在同一个抽象维度。
- **scripts/tests 是产物,不是层**:`_2_scripts/` 是操作 `_0_CorpAI` 和 DB 的运维工具,`_4_tests/` 是验证 `_0_CorpAI` 和 `_1_plugins/` 的代码。它们是被使用方,不是抽象分层。

---

## 历史

- 2026-08:加层编号前,所有顶层目录是无前缀字母序(API / corpai / plugins / scripts / sql / static / tests),新人 onboarding 难分主次
- 2026-08:加 `_0_`–`_5_` 编号 + 顶层 `CorpAI/` → `_0_CorpAI/` 重命名,目录顺序固定
- 2026-08:统一 `_0_CorpAI/` 内部 4 层编号
- 2026-08:plugin manifest endpoint 统一到 `:8001` / `:8030` / 5 个 sre_copilot 端口,跟实际 FastMCP server 对齐
- 2026-08:MCP 协议升级:从 python-a2a 私有 FastMCP → Anthropic 官方 spec(fastmcp 3.x + MCP SDK 2.x,JSON-RPC 2.0 over StreamableHTTP)
- 2026-08:`bridges.py` 同步/异步双接口(从 sync-over-async hack 改为干净 `asyncio.run()` + 明确错误信息)
- 2026-08:3 个 plugin 加 `[build-system] hatchling` + `[tool.hatch.build.targets.wheel]`,废弃 `pip install -e ./_1_plugins/<name>/src` 的脆弱方式
- 2026-08:plugin 测试目录改名 `tests/` → `<plugin>_tests/`,打破 pytest 一起跑的 ImportPathMismatchError

---

## 怎么改

如果未来要:
- **加新插件**:`_1_plugins/<name>/` + 在 `_0_CorpAI/_2_platform/plugin_manager.py` 注册 entry_points
- **加新层**(如独立 `docs/`):用下一个空闲编号,**不要**插在中间
- **加新文件类型**(如 `assets/`):用下一个空闲编号,或保持不编号(如 `_0_CorpAI/static/` 在 v3.5 已搬到顶层)

---

## 相关 ADR

- `docs/adr/` — 架构决策记录(plugin registration / RBAC 模型 / 记忆分层 / observability 等)
- 命名约定没有独立 ADR,但跟 **ADR-0001 Clean Architecture 分层** 直接相关