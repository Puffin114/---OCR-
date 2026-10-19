# 文档抽取评测平台（doc-extract-eval-platform）

> 融创软通实训第十组 · 项目源代码
>
> ⚠️ **本仓库中所有配置信息（百度云 AK/SK、登录密码、OneAPI 密钥、内网数据库地址/账号、BOS 桶名等）均已做脱敏处理**，以占位符（如 `<YOUR_...>`）替代真实值。克隆后请在 `config.yaml` 中填入自己的凭证再运行。

## 一、项目背景

本项目是实训期间开发的一个**本地可运行的「文档抽取评测平台」**，用于量化评估文档结构化抽取（从 PDF / 图片中提取字段）的效果。它把"标注—抽取—评测—复核"的完整链路产品化，形成可复用的评测闭环：

**数据集加载 → 人工二次标注 → 调用公有云文档抽取 → 结果对比与指标计算 → 自定义评测标准 + 人工复核 → 重算复核后指标**

评测结果展示仿照内网评测平台风格：综合指标 / 各字段柱状图 + 效果指标表 + 「查看评测结果」左右对比视图。

## 二、核心功能

- **用户登录鉴权**：账号密码登录；后端对所有 `/api/*` 做登录校验；每次刷新/直达子页面均需重新登录。
- **数据集管理**：工作区数据集加载、创建数据集（有标注 zip / 未标注原文件两种导入，支持大文件分片上传）、字段清单编辑（含组合字段）、字段标注统计。
- **二次标注**：文档查看器框选 → 自动识别框内文本填入字段 → 单字段与组合字段分组标注。
- **评测任务**：逐篇调用百度智能云「文档抽取」异步 OpenAPI（提交→轮询），结果入库并计算指标；支持复制任务。
- **指标与可视化**：综合指标（准确率/召回率/F1）、各字段指标、性能指标；原始 vs 人工复核后并列。
- **查看评测结果 + 人工复核**：标注/预测叠加彩色框、字段对比表、不一致高亮；可配置匹配规则（精确/去空格标点/忽略大小写/日期归一化/数字归一化/包含/正则）；逐行"一致/不一致"人工覆盖判定并重算指标。
- **配置中心**：云平台凭证管理（AK/SK 掩码）、模型服务登记。
- **数据回流（实验性，入口暂时下线）**：从业务库 + 对象存储回流文档的能力，相关前端入口当前已注释，保留后端代码以便后续接入场景化回流。

## 三、技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | React 18 + TypeScript + Vite 5 + Ant Design 5 + ECharts 5 + React Router 6 + axios + pdfjs-dist |
| 后端 | Python + FastAPI + Uvicorn + SQLite + PyMuPDF(fitz) + httpx + PyYAML + openpyxl |
| 外部服务 | 百度智能云：OAuth 鉴权、文档抽取 OpenAPI、通用文字识别 OCR |

<!-- APPEND -->

## 四、目录结构

```
.
├── README.md               ← 本文件
├── .gitignore
├── config.example.yaml     ← 配置模板
├── config.yaml             ← 配置文件（已脱敏，请填入自己的凭证）
├── backend/                ← FastAPI 后端
│   ├── main.py config.py db.py models.py requirements.txt
│   ├── routers/            ← auth / datasets / documents / annotations / eval_tasks / metrics / review / settings / backflow
│   └── services/           ← dataset / annotation / cloud / eval / backflow 服务
└── frontend/               ← React + TS + Vite + Ant Design + ECharts
    ├── index.html  package.json  tsconfig.json  vite.config.ts
    └── src/
        ├── App.tsx  main.tsx  index.css  api/
        ├── components/     ← DocViewer / CriteriaEditor / MetricBarChart
        └── pages/          ← Login / DatasetList / CreateDataset / Annotate / EvalTask* / EvalResult / Settings / Backflow*
```

> 说明：为控制体积，本包**不含依赖与运行期文件**（`node_modules/`、`.venv/`、内置 Node 运行时、`frontend/dist/` 构建产物、`.data/` 运行期数据、以及导出的 `*.xlsx` / `*.zip` 等数据文件均未包含）。依赖请按下文自行安装。数据集与代码分离存放，不随源码提供。

## 五、配置说明（已脱敏）

所有凭证集中在 `config.yaml`，运行前请把占位符替换为真实值：

| 配置项 | 说明 |
| --- | --- |
| `cloud.api_key` / `cloud.secret_key` | 百度智能云「文档抽取」AK/SK（`<YOUR_BAIDU_API_KEY>` / `<YOUR_BAIDU_SECRET_KEY>`） |
| `cloud.*_url` | 鉴权 / 提交 / 查询 / OCR 接口地址（已填公网默认） |
| `paths.*` | 数据集三类目录与运行期存储目录（按需改为本地路径） |
| `auth.username` / `auth.password` | 登录账号密码（`admin` / `<YOUR_LOGIN_PASSWORD>`） |
| `oneapi.api_key` / `api_base` / `model` | OpenAI 兼容网关，仅后端使用（均为占位符） |

> 代码中涉及的内网数据库地址、只读账号、BOS 桶名（见 `backend/services/backflow_service.py` 的 `EXTRACT_SCENE`）同样已替换为 `<YOUR_...>` 占位符。

## 六、运行方式

**后端**（Python 3.9+）：
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # 可选
pip install -r requirements.txt
# 回到项目根目录，确保 config.yaml 已填好凭证
python -m uvicorn main:app --port 8000
```

**前端**（Node 18+）：
```bash
cd frontend
npm install
npm run dev          # 开发模式，默认 http://localhost:5173
# 或构建后由后端托管：
npm run build        # 产物在 frontend/dist，启动后端后访问 http://localhost:8000
```

## 七、使用流程

1. **登录**：用 `config.yaml` 中配置的账号密码登录。
2. **加载 / 创建数据集**：加载工作区数据集，或上传数据创建（有标注 zip / 未标注原文件）。
3. **二次标注**（可选）：框选文档区域，自动识别文本填入字段。
4. **新建评测任务**：选文件与字段、配匹配规则 → 后台调用文档抽取 → 自动算指标。
5. **查看指标**：综合 / 各字段 / 性能指标，原始与人工复核后并列。
6. **查看评测结果 + 人工复核**：对比标注与预测、配置评测标准、逐行"一致/不一致"覆盖判定、重新计算。

## 八、说明与注意

- **额度提示**：百度云 AK/SK 多为个人额度（约 100 张），评测会逐篇消耗额度，请按需控制评测规模。
- **安全**：请勿把填好真实凭证的 `config.yaml` 提交到公开仓库（`.gitignore` 已默认忽略 `config.yaml`）。
- **数据回流入口**：当前前端「回流数据 / 回流数据集列表」按钮已注释下线，后端相关代码保留，后续如需接入"场景化回流"可恢复。

