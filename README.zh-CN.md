# MeetingMind

MeetingMind 是一个本地优先的中文会议音频整理项目。

截至 2026 年 9 月 17 日：

- 第一阶段：FastAPI 最小闭环，已完成
- 第二阶段：FFmpeg + WhisperX 中文转录，已完成
- 第三阶段：MySQL 8 持久化，已完成
- 第四阶段：AI 分析后端已完成，并已通过真实 OpenAI + MySQL 链路验证
- 第五阶段：说话人映射、Outlook 兼容 ICS、Markdown 导出、启动恢复、Gold Standard 评估、AI 草稿审计、阶段耗时记录和 GitHub Actions 已完成
- 前端已切换至真实 FastAPI HTTP API（开发环境通过 Vite 代理）
- 已接入 WhisperX + pyannote 自动说话人分离，并保留人工说话人姓名映射
- 第六阶段异步队列和故障恢复已完成；第七阶段发布级检查、真实运行态验收与故障恢复验收已完成，当前为本地单机发布候选
- 第八阶段进行中：部署级 Bearer 访问令牌和本机 HTTPS/Caddy 反向代理边界已完成；下一项为备份与恢复
- Outlook Classic 已完成 ICS 实际导入验收，中文内容和 Asia/Shanghai 时间转换正确



第七阶段说明见 `D:\MeetingMind\docs\第七阶段开发说明.md`；第八阶段说明见 `D:\MeetingMind\docs\第八阶段开发说明.md`；接口文档见 `D:\MeetingMind\docs\OpenAPI使用说明.md`；演示脚本见 `D:\MeetingMind\docs\演示材料.md`；可重复执行的发布前检查见 `D:\MeetingMind\docs\发布前检查清单.md`。 本次本地检查记录见 `D:\MeetingMind\docs\发布前检查记录-2026-09-17.md`。

完整设计基线见 `D:\MeetingMind\MeetingMind开发设计文档.md`，后端说明见 `D:\MeetingMind\backend\README.md`。

统一运行数据目录的迁移与复验记录见 `D:\MeetingMind\docs\运行数据目录迁移记录-2026-09-17.md`。

隐私、外部模型传输与无自动脱敏边界见 `D:\MeetingMind\docs\隐私与数据边界.md`。 访问控制与部署边界见 `D:\MeetingMind\docs\访问控制与部署边界.md`。 HTTPS 与反向代理见 `D:\MeetingMind\docs\HTTPS与反向代理.md`。 验证记录见 `D:\MeetingMind\docs\HTTPS反向代理验证记录-2026-09-17.md`。 验证记录见 `D:\MeetingMind\docs\访问控制验证记录-2026-09-17.md`。 验证记录见 `D:\MeetingMind\docs\隐私数据边界验证记录-2026-09-17.md`。

## 前端快速启动

先启动后端，再启动前端。前端会把 `/api` 请求代理到 `http://127.0.0.1:8000`：

```powershell
cd D:\MeetingMind\frontend
npm install
npm run dev
```

## 后端快速启动

```powershell
cd D:\MeetingMind
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "D:\MeetingMind\backend"
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

## 第五阶段验证摘要

截至 2026 年 9 月 17 日：

- 后端自动化测试：`57 passed`（以 2026 年 9 月 17 日本机 HTTPS 边界检查为准）；
- 前端 Vitest 单元测试：`18 passed`；
- 前端类型检查和生产构建：通过；
- 三组受控 Gold Standard：结构化输出成功率、待办 Precision/Recall、负责人、日期和状态指标均为 `1.0`；
- 中断音频任务可在服务重启后从原始音频自动恢复；
- Outlook ICS 使用 `VEVENT`、UTF-8 BOM、CRLF 和 UTF-8 字节级折行。

评估样本规模很小，只用于回归和项目验收，不代表生产环境准确率。评估方法与结果见 `D:\MeetingMind\evaluation\README.md` 和 `D:\MeetingMind\evaluation\reports\latest.json`。


## 第五阶段新增：阶段耗时

处理任务会把每次阶段进入和离开的时间边界写入 `processing_stage_events`，避免使用更新时间伪造耗时。记录包含阶段、自动恢复尝试编号、开始时间、结束时间、耗时和结果。旧任务在迁移后不会补算历史耗时，新任务从迁移完成后开始记录。

升级数据库：

```powershell
cd D:\MeetingMind
$env:PYTHONPATH = "D:\MeetingMind\backend"
backend\.venv\Scripts\alembic -c backend\alembic.ini upgrade head
```
