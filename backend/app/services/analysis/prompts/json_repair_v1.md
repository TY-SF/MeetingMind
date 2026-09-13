将上一份模型输出修复为符合 MeetingAnalysisDraft Schema 的 JSON。只修复格式、字段名、缺失的必填字段和枚举值，不增加原输出没有依据的会议事实。无法确定的可空字段填 null，数组缺失时填空数组。只返回 JSON。
