# MeetingMind Gold Standard 评估

本目录提供第五阶段的三组受控回归样本：

1. 清晰、结构化的双人技术会议；
2. 包含建议、分歧和未确定表达的会议；
3. 包含噪音标记、重叠发言、英文术语和提示注入文本的会议。

评估指标包括结构化输出成功率、明确待办 Precision/Recall、负责人及负责人状态准确率、日期标准化准确率和结论状态准确率。匹配依据是每条 Gold Standard 中公开、可检查的关键词集合，而不是另一个模型的主观评分。

## 使用当前配置重新调用模型

```powershell
cd D:\MeetingMind
backend\.venv\Scripts\python.exe evaluation\run_openai.py
```

脚本读取 `backend/.env/meetingmind.env`，但不会把 API Key、Token 或数据库密码写入预测结果和报告。

## 仅重新计算指标

```powershell
backend\.venv\Scripts\python.exe evaluation\evaluate.py
```

当前报告位于 `evaluation/reports/latest.json`。三组受控样本只用于项目回归和演示，不具有生产环境统计代表性，也不能替代更大规模、真实授权音频上的评估。

## 第七天三组音频端到端验收

第七天验收不再只从预制转录 JSON 开始。项目提供三组可重复生成的非敏感合成音频，覆盖：

1. 清晰的结构化双人会议；
2. 建议、分歧和未确定表达；
3. 轻微背景噪音、短暂重叠发言和英文技术术语。

音频文件写入被 Git 忽略的 `data/evaluation/day7-audio/`，不会把录音或运行中转录提交到仓库。生成命令：

```powershell
cd D:\MeetingMind
.\scripts\generate_day7_audio_fixtures.ps1
```

在 MySQL、Redis、API 和 RQ Worker 已启动后，执行完整链路：

```powershell
backend\.venv\Scripts\python.exe evaluation\run_end_to_end.py
```

每组样本都会实际执行：上传、Redis/RQ、FFmpeg、WhisperX 转录与对齐、pyannote 说话人分离、姓名映射、OpenAI 结构化分析、Markdown/ICS 导出以及删除完整性验证。运行结束后默认永久删除临时会议。

可提交的脱敏证据位于 `evaluation/reports/day7-e2e-latest.json`。它只保存哈希、阶段状态、计数、模型元数据和聚合指标，不保存访问令牌、音频正文、完整转录、会议摘要或模型原始响应。验证命令：

```powershell
backend\.venv\Scripts\python.exe evaluation\verify_day7_e2e_report.py
```

三组样本仍然只用于项目回归与第七天验收，不具有生产环境统计代表性。
