# MeetingMind Gold Standard 评估

本目录提供第五阶段的三组受控回归样本：

1. 清晰、结构化的双人技术会议；
2. 包含建议、分歧和未确定表达的会议；
3. 包含噪音标记、重叠发言、英文术语和提示注入文本的会议。

评估指标包括结构化输出成功率、明确待办 Precision/Recall、负责人及负责人状态准确率、日期标准化准确率和结论状态准确率。匹配依据是每条 Gold Standard 中公开、可检查的关键词集合，而不是另一个模型的主观评分。

## 使用当前配置重新调用模型

```powershell
cd D:\MeetingMind
backend\.venv\Scripts\python.exe evaluationun_openai.py
```

脚本读取 `backend/.env/meetingmind.env`，但不会把 API Key、Token 或数据库密码写入预测结果和报告。

## 仅重新计算指标

```powershell
backend\.venv\Scripts\python.exe evaluation\evaluate.py
```

当前报告位于 `evaluation/reports/latest.json`。三组受控样本只用于项目回归和演示，不具有生产环境统计代表性，也不能替代更大规模、真实授权音频上的评估。
