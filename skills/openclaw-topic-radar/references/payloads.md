# Minimal Payloads

## `user_topic`

```json
{
  "request_id": "req-user-topic-demo",
  "trigger_source": "manual",
  "user_topic": {
    "topic": "OpenAI 企业级智能体平台",
    "company": "OpenAI",
    "keywords": ["智能体", "企业服务"]
  },
  "entry_options": {
    "input": {
      "mode": "user_topic"
    },
    "write": {
      "executor": "external_writer"
    },
    "delivery": {
      "target_mode": "archive_only",
      "target": "archive://openclaw_p0"
    },
    "degrade": {
      "input_unavailable": "fail",
      "write_unavailable": "fail",
      "delivery_unavailable": "fail"
    }
  }
}
```

## `real_source`

```json
{
  "request_id": "req-real-source-demo",
  "trigger_source": "manual",
  "entry_options": {
    "input": {
      "mode": "real_source",
      "source_ids": ["weibo"],
      "limit": 5
    },
    "write": {
      "executor": "external_writer"
    },
    "delivery": {
      "target_mode": "archive_only",
      "target": "archive://openclaw_p0"
    },
    "degrade": {
      "input_unavailable": "fail",
      "write_unavailable": "fail",
      "delivery_unavailable": "fail"
    }
  }
}
```

## `inline_topic_cards`

```json
{
  "request_id": "req-inline-topic-cards-demo",
  "trigger_source": "manual",
  "topic_cards": [
    {
      "event_id": "evt-demo-001",
      "topic_title": "OpenAI 企业级智能体平台",
      "summary": "围绕企业级智能体协作与审计能力形成的选题卡。"
    }
  ],
  "entry_options": {
    "input": {
      "mode": "inline_topic_cards"
    }
  }
}
```

## `deliver_only`

```json
{
  "request_id": "req-deliver-only-demo",
  "trigger_source": "manual",
  "decision_status": "publish_ready",
  "delivery_target": "archive://openclaw_p0",
  "content_bundle": {
    "event_id": "evt-demo-001",
    "content_status": "generated",
    "evidence_pack": {},
    "title": {"text": "示例标题"},
    "draft": {"body_markdown": "示例正文"},
    "summary": {"text": "示例摘要"}
  }
}
```

## CLI continuation examples

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --topic-cards-file topic_cards.json --execution-mode resume
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --normalized-events-file normalized_events.json --execution-mode resume
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --scored-events-file scored_events.json --execution-mode write_only
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --content-bundle-file content_bundle.json --execution-mode deliver_only
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --content-bundles-file content_bundles.json --execution-mode deliver_only
```
