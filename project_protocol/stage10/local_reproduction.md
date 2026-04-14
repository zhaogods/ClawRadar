# 阶段十历史本地复现说明

## 1. 复现目标
在本地稳定复现阶段十历史演示包的统一入口主链路，并生成与该历史留档口径一致的输入样本、结果快照与本地交付留档。

本说明的定位是 历史复现材料，不是下一阶段产品化运行入口已经完成的使用手册。

## 2. 复现前提
- 当前工作区根目录为 [`f:/02_code/ClawRadar`](task_plan.md)
- Python 环境可在项目根目录下直接导入 [`clawradar`](clawradar/__init__.py)
- 不要求真实外部交付渠道可用
- 不要求真实来源在线可用
- 不要求原项目外部写作执行环境可用

## 3. 历史演示采用的复现策略
- 输入基底使用准真实样本 [`tests/fixtures/openclaw_p0_score_publish_ready_input.json`](tests/fixtures/openclaw_p0_score_publish_ready_input.json)
- 统一入口使用 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)
- 写作执行固定为 `openclaw_builtin`
- 交付目标固定为 `archive_only`
- 留档根目录固定为 [`project_protocol/stage10/demo_runs/`](project_protocol/stage10/demo_runs/)

## 4. 历史复现命令
在项目根目录执行以下命令：

```bash
python -c "import json; from pathlib import Path; from clawradar.orchestrator import topic_radar_orchestrate; base=Path('tests/fixtures/openclaw_p0_score_publish_ready_input.json'); payload=json.loads(base.read_text(encoding='utf-8')); payload['request_id']='req-stage10-demo-001'; payload['entry_options']={'delivery': {'target_mode': 'archive_only', 'target': 'archive://stage10-demo'}, 'write': {'executor': 'openclaw_builtin'}}; result=topic_radar_orchestrate(payload, delivery_time='2026-04-12T06:46:00Z', runs_root=Path('project_protocol/stage10/demo_runs')); out_dir=Path('project_protocol/stage10/generated'); out_dir.mkdir(parents=True, exist_ok=True); (out_dir/'demo_input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8'); (out_dir/'demo_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'); print(json.dumps({'run_status': result.get('run_status'), 'final_stage': result.get('final_stage'), 'decision_status': result.get('decision_status'), 'entry_resolution': result.get('entry_resolution'), 'delivery_receipt': result.get('delivery_receipt'), 'artifact_summary': result.get('artifact_summary')}, ensure_ascii=False, indent=2))"
```

## 5. 预期生成文件
执行后应能看到以下历史文件或目录：
- 输入样本：[`project_protocol/stage10/generated/demo_input.json`](project_protocol/stage10/generated/demo_input.json)
- 统一结果快照：[`project_protocol/stage10/generated/demo_result.json`](project_protocol/stage10/generated/demo_result.json)
- 留档目录：[`project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/`](project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/)
- 留档快照：[`project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/payload_snapshot.json`](project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/payload_snapshot.json)
- 审核消息快照：[`project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/feishu_message.json`](project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/feishu_message.json)

## 6. 预期关键结果
- [`project_protocol/stage10/generated/demo_result.json`](project_protocol/stage10/generated/demo_result.json) 中应满足：
  - `run_status=completed`
  - `final_stage=deliver`
  - `decision_status=publish_ready`
  - `entry_resolution.delivery.target_mode=archive_only`
  - `stage_statuses.deliver.status=succeeded`
  - `event_statuses[0].deliver_status=archived`
- [`payload_snapshot.json`](project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/payload_snapshot.json) 中应保留 `normalized_events`、`timeline`、`evidence_pack`、`scorecard`、`content_bundle`
- [`feishu_message.json`](project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/feishu_message.json) 中应保留摘要、稿件预览、不确定性提示与交付目标

## 7. 与下一阶段目标的区分
本复现说明对应的是 阶段十历史路径，即 准真实样本 + 本地真实运行 + 本地真实留档。

本复现说明不自动等同于以下内容已经完成：
- 面向真实使用者的总启动入口
- 双输入模式，即 真实来源输入 与 用户主题输入 并存
- 显式选题阶段
- 全流程运行 与 分阶段运行
- 标准阶段工件与基于工件继续执行

这些内容属于阶段十之后新增的正式目标，应以后续协议文件为准。

## 8. 真实性边界
- 本复现说明不把真实来源在线抓取、`external_writer` 实跑或真实外部渠道外发表达为阶段十已完成步骤
- 阶段七至阶段九中与真实来源接入、原项目写作接入、外部交付 fallback 相关的能力事实，仍以代码与测试为依据
- 本文档只说明阶段十历史复现路径本身
