# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Working in this repo

ClawRadar is a Python pipeline for real-source topic discovery, scoring, writing, and delivery. The current root flow is the `clawradar` package; `radar_engines/` is the retained capability layer that `clawradar` calls into for crawling and report generation.

## Common commands

Top-level setup:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest
```

Run the main test suite:

```bash
python -m pytest tests
```

Run one test file:

```bash
python -m pytest tests/test_clawradar_automation.py
```

Run one test case or test method:

```bash
python -m pytest tests/test_clawradar_automation.py -k "test_manual_full_pipeline_runs_all_stages_and_backfills_statuses"
```

Run the main launcher:

```bash
python run_clawradar_deliverable.py --input-mode real_source --source-ids weibo --limit 5
python run_clawradar_deliverable.py --input-mode user_topic --topic "AI 智能体治理" --company "OpenAI" --keywords 治理 审计
```

Replay an existing publish output:

```bash
python run_clawradar_deliverable.py --publish-only --delivery-channel wechat --delivery-target "wechat://draft-box/clawradar-review"
```

Run the real-source demo:

```bash
python scripts/run_real_source_demo.py
```

MindSpider-only local workflow:

```bash
cd radar_engines/MindSpider
pip install -r requirements.txt
playwright install
python main.py --status
python main.py --broad-topic
python main.py --deep-sentiment --test
python main.py --complete --test
```

Notes on lint/build:

- There is no dedicated repo-wide build or lint task file in this checkout.
- `requirements.txt` includes `black` and `flake8`, so run them directly if you need formatting or lint checks.

## Architecture at a glance

### Main pipeline

`clawradar/__init__.py` re-exports the public API. The primary entry point is `clawradar.orchestrator.topic_radar_orchestrate()`.

The pipeline is organized as:

1. `clawradar/contracts.py` — normalize and validate ingest payloads.
2. `clawradar/real_source.py` and `clawradar/topics.py` — bridge into `radar_engines/` or turn a user topic into crawlable candidates.
3. `clawradar/scoring.py` — build timelines, facts, risk flags, and the publish decision.
4. `clawradar/writing.py` — generate or rewrite the content bundle, optionally via `ReportEngine`.
5. `clawradar/delivery.py` — package delivery payloads and archive outputs.
6. `clawradar/publish_only.py` — replay an existing write output without rerunning earlier stages.

### Capability layer

`radar_engines/` still holds the larger engine implementations:

- `MindSpider` for source discovery and crawling
- `QueryEngine` for search
- `MediaEngine` for multimedia search
- `ReportEngine` for report generation and rendering
- `config.py`, `utils/`, and `static/` as shared support code

### Output model

The orchestrator writes run artifacts under `outputs/<input_mode>/<run_id>/`.

Each input mode root also keeps `outputs/<input_mode>/latest.json` pointing at the latest run summary.

A run directory contains:

- `summary.json`
- `reports/`
- `debug/`
- `recovery/`

`debug/` is the main trace directory for orchestration snapshots such as `input.json`, `entry_resolution.json`, `stage_statuses.json`, `artifact_summary.json`, `crawl.json`, `topics.json`, `ingest.json`, `score.json`, `content_bundles.json`, `write.json`, `delivery_receipt.json`, and `deliver.json`.

`recovery/` stores per-event delivery archives such as `payload_snapshot.json`, `scorecard.json`, channel message payloads, and `recovery_summary.json`.

`clawradar/publish_only.py` prefers this mode-first layout and still retains compatibility with older legacy outputs when replaying existing artifacts.

### Delivery and publishing

- WeChat publisher code lives under `clawradar/publishers/wechat/`.
- WeChat credentials are channel-local, not repo-root `.env` files.
- `run_clawradar_deliverable.py` defaults to `archive_only` delivery unless told otherwise.

## What to inspect first

If you need to understand a change quickly, start with:

1. `run_clawradar_deliverable.py`
2. `clawradar/orchestrator.py`
3. `clawradar/contracts.py`
4. `clawradar/scoring.py`
5. `clawradar/writing.py`
6. `clawradar/delivery.py`
7. `tests/test_clawradar_automation.py`
