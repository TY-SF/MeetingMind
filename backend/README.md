# MeetingMind 后端

隐私、数据外发和无自动脱敏边界见 `D:\MeetingMind\docs\隐私与数据边界.md`。上传和每次 AI 分析都要求显式确认。

## 当前阶段：第八阶段部署边界加固

截至 2026 年 9 月 17 日，第一至第七阶段已完成；第八阶段的部署级访问控制和本机 HTTPS/Caddy 反向代理边界已完成，下一项为备份与恢复。已验证：

- OpenAI Responses API Provider 抽象
- Pydantic 严格结构化输出 Schema
- 中文会议摘要、结论、待办的数据模型
- 相对日期解析与 UTC 标准化
- AI 原始响应、Provider、模型和 Prompt 版本持久化
- `GET /analysis` 查询分析结果
- `POST /analysis` 生成或重新生成 AI 草稿
- `PATCH /analysis` 人工审核并整体保存
- `version` 乐观并发控制，过期版本返回 `409 Conflict`
- AI 错误码映射和失败状态保存
- SQLite Repository/API 自动化测试
- OpenAI Python SDK 依赖
- 真实中文 MP3 的 WhisperX 转录 → OpenAI 结构化分析 → MySQL 持久化
- 真实人工审核 PATCH、过期版本 `409` 与测试记录删除验证

当前自动化测试结果：`57 passed`（2026 年 9 月 17 日本机 HTTPS 边界检查）。

## 数据库

默认生产配置使用本地 MySQL 8，自动化测试使用隔离的 SQLite。当前七张业务表：

```text
meetings
processing_jobs
transcript_segments
meeting_analyses
decisions
action_items
processing_stage_events
```

AI 原始响应保存在 `meeting_analyses.ai_raw_result`，人工审核后的当前结果保存在摘要、结论和待办关系表中。人工修改不会覆盖原始 AI 响应快照。

## 本地配置

当前统一运行数据根目录为 `D:\MeetingMind\data`：日志、发布检查报告和会议文件分别位于 `data/logs`、`data/release-check` 和 `data/meetings`。从旧版本升级且仍存在项目根目录 `meetings` 时，先执行：

```powershell
backend\.venv\Scripts\python.exe scripts\migrate_runtime_layout.py
backend\.venv\Scripts\python.exe scripts\migrate_runtime_layout.py --apply
```

第一条命令只显示迁移计划；第二条命令在确认无目标冲突后移动目录。`backend/data` 与 `backend/meetings` 属于早期开发测试资产，不是当前运行目录。

实际配置文件不进入版本库：

```text
D:\MeetingMind\backend\.env\meetingmind.env
```

发布配置必须生成至少 32 个字符的高熵访问令牌：

```env
MEETINGMIND_API_TOKEN=本机生成的随机值
```

业务 API 要求 `Authorization: Bearer <token>`；健康存活、数据库就绪、认证状态和 OpenAPI 文档保持公开。完整说明见 `D:\MeetingMind\docs\访问控制与部署边界.md`。

MySQL 配置：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=meetingmind
MYSQL_USER=你的用户名
MYSQL_PASSWORD=你的密码
```

OpenAI 与说话人分离配置：

```env
OPENAI_API_KEY=在本机填写你的API密钥
LLM_MODEL=gpt-5.6-terra
LLM_BASE_URL=
LLM_TIMEOUT_SECONDS=120
LLM_MAX_INPUT_CHARS=120000
MEETINGMIND_DIARIZATION_ENABLED=true
MEETINGMIND_DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
HF_TOKEN=在本机填写 Hugging Face Token
```

不要在聊天、截图或 Git 提交中暴露真实 API Key。直连 OpenAI 时 `LLM_BASE_URL` 保持为空；使用兼容服务时才填写。模型 ID 是否对当前 API 项目开放，需要通过真实请求确认。

## 安装依赖

完整运行环境需要 API 与 WhisperX/pyannote 依赖：

```powershell
cd D:\MeetingMind
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

如需指定 CUDA 版本，请先按 `backend/requirements-whisperx.txt` 中的说明安装匹配的 PyTorch/Torchaudio，再安装上述依赖。仅执行不加载音频模型的 API 单元测试时，可只安装 `backend/requirements-api.txt`。

## 启动 API

开发环境已允许 `FRONTEND_ORIGIN` 配置的前端跨域请求，并允许 `Authorization` 请求头；Vite 同时将 `/api` 默认代理至 `http://127.0.0.1:8000`。

```powershell
cd D:\MeetingMind
$env:PYTHONPATH = "D:\MeetingMind\backend"
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

- API：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

本机安全入口：

```powershell
.\scripts\start_secure_edge.ps1
```

默认访问 `https://localhost:8443`；内部 CA 未加入系统信任库时浏览器会提示证书不受信任。详见 `D:\MeetingMind\docs\HTTPS与反向代理.md`。 验证记录见 `D:\MeetingMind\docs\HTTPS反向代理验证记录-2026-09-17.md`。

## 第四阶段接口

```http
GET   /api/v1/meetings/{meeting_id}/analysis
POST  /api/v1/meetings/{meeting_id}/analysis
PATCH /api/v1/meetings/{meeting_id}/analysis
```

`POST` 需要会议已经有转录、本机已配置 OpenAI API Key，并在请求体中显式确认本次转录外发：

```json
{
  "analysis_data_confirmed": true
}
```

未确认时返回 `422 ANALYSIS_DATA_CONFIRMATION_REQUIRED`。未配置密钥时返回：

```json
{
  "detail": {
    "code": "MODEL_AUTH_ERROR",
    "message": "未配置 OpenAI API Key；请配置后再执行分析"
  }
}
```

`PATCH` 用于保存人工审核后的完整草稿。请求中的 `version` 必须等于数据库当前版本：

```json
{
  "summary": "人工审核后的会议摘要",
  "decisions": [],
  "action_items": [],
  "version": 1
}
```

保存成功后版本递增；版本过期返回 `409` 和 `ANALYSIS_VERSION_CONFLICT`。

## 迁移

```powershell
cd D:\MeetingMind
$env:PYTHONPATH = "D:\MeetingMind\backend"
backend\.venv\Scripts\alembic -c backend\alembic.ini upgrade head
backend\.venv\Scripts\alembic -c backend\alembic.ini current
```

当前迁移版本：`0007_one_job_per_meeting`。第五阶段使用独立迁移新增阶段耗时事件表，并为时间边界保留微秒精度；不要修改已经应用的旧迁移。

## 自动化测试

```powershell
cd D:\MeetingMind
$env:PYTHONPATH = "D:\MeetingMind\backend"
backend\.venv\Scripts\python.exe -m pytest -q
```

覆盖：上传 API、SQLite/MySQL Repository 基础行为、日期解析、结构化分析规范化、超长输入、分析持久化、替换旧结果、乐观锁冲突、人工审核 PATCH、无 API Key 错误路径。

## 第五阶段已完成内容

截至 2026 年 9 月 10 日，第五阶段已完成本地开发与自动化验证：

- `PATCH /api/v1/meetings/{meeting_id}/speakers` 说话人姓名映射
- 保留 `speaker_label` 原始标签，同时用 `speaker_name` 作为显示名
- `GET /api/v1/meetings/{meeting_id}/exports/markdown` 后端 Markdown 下载
- `GET /api/v1/meetings/{meeting_id}/exports/calendar` Outlook 兼容的 ICS `VEVENT` 下载；下载文件带 UTF-8 BOM，避免 Outlook 导入路径按系统代码页错误解码中文
- ICS 仅导出具有 `EXPLICIT` 或 `CONFIRMED` 截止时间的待办，并表示为截止前 1 小时开始、截止时结束的透明日历事件
- 导出在响应中即时生成，不额外把 Markdown/ICS 副本写入磁盘
- Vite 前端真实下载入口和转录页说话人映射编辑器
- 前端 API 契约、HTTP 映射和错误处理同步更新
- 说话人映射、Markdown、ICS、导出错误路径自动化测试
- 服务启动时自动扫描中断的音频任务；源文件存在时从不可变源音频重新执行，缺失时返回稳定错误码 `SOURCE_FILE_MISSING`
- 处理任务返回 `error_code` 和 `retry_count`，前端明确显示自动恢复次数和稳定错误码
- 三组 Gold Standard 结构化分析评估及可重复执行脚本
- 2026 年 9 月 9 日使用当前 OpenAI 配置完成三组评估：结构化输出、待办 Precision/Recall、负责人、日期和状态指标在该受控样本上均为 `1.0`
- 上述三组结果只代表受控回归样本，不代表生产性能

第五阶段自动化验证结果：后端 `37 passed`，前端 Vitest `13 passed`，前端 `npm run build` 通过。新增审计接口、阶段耗时记录和前端映射组件测试。

## 真实端到端验证结果

2026 年 9 月 10 日已使用用户提供的真实中文会议 MP3 完成临时验证：

```text
MP3 上传 → FFmpeg/WhisperX 转录（42,121 ms，3 个片段）
→ pyannote 自动分离出 3 位说话人（SPEAKER_00/01/02）
→ OpenAI Responses API + gpt-5.6-terra 结构化分析
→ MySQL 保存摘要、1 条未决结论与原始 AI 响应
→ PATCH 人工审核保存（version: 1 → 2）
→ 使用旧 version 写入，得到 409 ANALYSIS_VERSION_CONFLICT
→ DELETE 清理临时数据库记录和本地会议目录
```

验证中没有保留临时会议记录、转录、分析响应文件或 API Key。

## 当前边界

- 前端已在开发环境默认通过 Vite `/api` 代理调用真实后端；请在 `D:\MeetingMind\frontend` 执行 `npm run dev`。
- 本机已提供 HTTPS/Caddy 静态前端和 API 反向代理；真实部署仍需实际域名、可信证书、防火墙和续期告警，多人环境还需要正式身份和角色授权。
- 生产任务使用 Redis + RQ；Windows Worker 通过 `scripts\start_rq_worker.ps1` 默认以兼容 RQ 2.6.x 的 `rq.worker.SimpleWorker` 启动；Linux/macOS 使用 `rq.worker.SpawnWorker`。需要后台常驻时使用 `scripts\start_rq_worker_background.ps1`。
- API 仅创建任务，实际音频处理在独立 Worker 中执行；Redis 不可用时 API 返回稳定错误码。




## 阶段耗时记录

`processing_stage_events` 持久化每次阶段执行的真实边界：`QUEUED`、`PREPROCESSING`、`TRANSCRIBING`、`DIARIZING`、`ANALYZING` 等阶段在状态切换时结束并计算耗时。自动恢复会保留原尝试并标记为 `INTERRUPTED`，新尝试使用递增的 `attempt` 编号。


## 有界日志与运行监控

API 与 RQ Worker 分别写入 `data/logs/api.jsonl` 和 `data/logs/worker.jsonl`。默认单文件 10 MiB、保留 5 个历史文件，可通过 `MEETINGMIND_LOG_MAX_BYTES` 和 `MEETINGMIND_LOG_BACKUP_COUNT` 调整。日志不得包含请求体、完整转录、模型原始响应或密钥。

后台启动与本机监控：

```powershell
cd D:\MeetingMind
.\scripts\start_api_background.ps1
.\scripts\start_rq_worker_background.ps1
.\scripts\check_operations.ps1 -TrustLocalCaddyCA
```

监控报告位于 `data/monitoring/latest.json`，退出码 0/1/2 分别代表 healthy/warning/critical。完整说明见 `docs/日志保留监控与告警.md`。
