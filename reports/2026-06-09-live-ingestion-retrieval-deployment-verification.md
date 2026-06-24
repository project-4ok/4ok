# GCB live ingestion, retrieval, and deployment verification evidence

Report started: 2026-06-09T19:19:26+02:00
Overall status: NOT COMPLETE — evidence collection in progress.

## Gate 1 — Baseline/runtime health
Status: IN PROGRESS

### Baseline command output
```text
timestamp=2026-06-09T19:19:26+02:00

--- GCB git status ---
## main...origin/main [ahead 17]
?? .hermes/
?? reports/

--- GCB latest commits ---
54afb5b (HEAD -> main) fix: restore sources when permission snapshots recover
1f4dc7b fix: make permissionless drive imports operator searchable
8485f96 (codex/retrieval-live-verification) fix: preserve google drive domain permissions
d54491a (codex/infra-deploy-recon) docs: add K3s deployment readiness runbook
aeb7348 (codex/openclaw-plugin) feat: add local openclaw plugin adapter
2659ccd (codex/recurring-live-ingestion) feat: add recurring live ingestion backfill
548f5cc (codex/agent-dx-diagnostics) feat: add agent-readable diagnostics
2d346e2 (codex/live-operator-idempotency) fix: make source record batches idempotent
f40096d fix: map local operator database host
dd193c3 test: reconcile live operator integration
b7016cf Add operator live ingestion command
7ae028e docs: de-emphasize fixture-backed operator paths

--- Infra git status ---
## main...origin/main

--- Infra latest commits ---
9b010dd (HEAD -> main, origin/main, origin/HEAD) Clarify OpenViking read level guidance
362d53e Preserve prod Slack DM routing on promotion
f48d5b2 Restore 4ok Jules model fallback
d0b7c57 Keep prod Slack DMs out of assistant threads
ce40e13 Retry Infisical CLI download in dev deploy workflow
77e5f3a Mount Codex auth bootstrap helper in gateway runtime
094af3c Allow prod gateway runtime secret read actions
c542a2a Stage Codex bootstrap helper in runtime bundle

--- Relevant Docker containers ---
4ok-dagster-webserver-1	Up 2 hours (healthy)	127.0.0.1:3001->3001/tcp
4ok-dagster-daemon-1	Up 2 hours (healthy)
4ok-dagster-code-1	Up 2 hours (healthy)	4000/tcp
4ok-dagster-postgres-1	Up 3 hours (healthy)	5432/tcp
4ok-postgres-1	Up 3 hours (healthy)	127.0.0.1:5432->5432/tcp
4ok-observability-1	Up 8 hours (healthy)	127.0.0.1:3000->3000/tcp, 127.0.0.1:4317-4318->4317-4318/tcp
4ok-cerbos-1	Up 8 hours (healthy)	127.0.0.1:3592-3593->3592-3593/tcp
4ok-honcho-1	Up 8 hours (healthy)	0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
4ok-honcho-db-1	Up 8 hours (healthy)	5432/tcp
4ok-graphiti-neo4j-1	Up 8 hours (healthy)	0.0.0.0:7474->7474/tcp, [::]:7474->7474/tcp, 0.0.0.0:7687->7687/tcp, [::]:7687->7687/tcp
4ok-honcho-redis-1	Up 8 hours (healthy)	6379/tcp

--- Runtime Postgres DB connectivity ---
/var/run/postgresql:5432 - accepting connections

--- source_records by source_system ---
acceptance	1
google_drive	21
linear	222
slack	29
twenty	203

--- retrieval_records by source_system ---
acceptance	1
google_drive	53
linear	224
slack	29
twenty	203

--- source lifecycle/permission summary ---
acceptance	deleted	current	1
google_drive	active	current	21
linear	active	current	222
slack	active	current	29
twenty	active	current	203
```

Interpretation: runtime DB is reachable if pg_isready reports accepting connections and counts above are present; final PASS/FAIL will be set after all baseline checks are interpreted.
## Gate 2 — Live ingestion proof
Status: IN PROGRESS

### Pre-run live ingestion status
```json
{
  "sources": {
    "google_drive": {
      "age_seconds": 2533,
      "connector_name": "google_drive-live",
      "error": "exit_code=1 Live Dagster import did not increase runtime DB rows: source_records_delta=0 retrieval_records_delta=53",
      "freshness_status": "failed",
      "idempotency_status": "",
      "latest_finished_at": "2026-06-09T16:37:32.476916+00:00",
      "latest_started_at": "2026-06-09T16:36:59.267412+00:00",
      "latest_status": "failed",
      "raw_output_ref": "",
      "source_record_count": null
    },
    "linear": {
      "age_seconds": null,
      "connector_name": "linear-live",
      "error": "",
      "freshness_status": "missing",
      "idempotency_status": "missing",
      "latest_finished_at": "",
      "latest_started_at": "",
      "latest_status": "missing",
      "raw_output_ref": "",
      "source_record_count": null
    },
    "slack": {
      "age_seconds": null,
      "connector_name": "slack-live",
      "error": "",
      "freshness_status": "missing",
      "idempotency_status": "missing",
      "latest_finished_at": "",
      "latest_started_at": "",
      "latest_status": "missing",
      "raw_output_ref": "",
      "source_record_count": null
    },
    "twenty": {
      "age_seconds": null,
      "connector_name": "twenty-live",
      "error": "",
      "freshness_status": "missing",
      "idempotency_status": "missing",
      "latest_finished_at": "",
      "latest_started_at": "",
      "latest_status": "missing",
      "raw_output_ref": "",
      "source_record_count": null
    }
  },
  "stale_after_minutes": 60,
  "status": "attention_required"
}
```

### Run live ingestion for all sources
```json
{
  "sources": [
    {
      "artifact_dir": ".local/recurring-live-ingestion/twenty",
      "connector_name": "twenty-live",
      "job_id": "44f9d946-dcaa-4f5f-858b-f3977e51576d",
      "record_count": null,
      "retrieval_record_count": null,
      "source": "twenty",
      "source_record_count": null,
      "status": "succeeded"
    },
    {
      "artifact_dir": ".local/recurring-live-ingestion/slack",
      "connector_name": "slack-live",
      "job_id": "960c8af9-9777-432f-92e2-20e869ad4ac3",
      "record_count": null,
      "retrieval_record_count": null,
      "source": "slack",
      "source_record_count": null,
      "status": "succeeded"
    },
    {
      "artifact_dir": ".local/recurring-live-ingestion/linear",
      "connector_name": "linear-live",
      "job_id": "741348fc-6370-488f-9e9d-56124ea189b7",
      "record_count": null,
      "retrieval_record_count": null,
      "source": "linear",
      "source_record_count": null,
      "status": "succeeded"
    },
    {
      "artifact_dir": ".local/recurring-live-ingestion/google_drive",
      "connector_name": "google_drive-live",
      "job_id": "b72d0bd2-ff16-42a7-9909-065b649018b6",
      "record_count": null,
      "retrieval_record_count": null,
      "source": "google_drive",
      "source_record_count": null,
      "status": "succeeded"
    }
  ],
  "status": "succeeded"
}
```

### Post-run live ingestion status
```json
{
  "sources": {
    "google_drive": {
      "age_seconds": 0,
      "connector_name": "google_drive-live",
      "error": "",
      "freshness_status": "fresh",
      "idempotency_status": "recorded",
      "latest_finished_at": "2026-06-09T17:20:38.242794+00:00",
      "latest_started_at": "2026-06-09T17:20:01.129182+00:00",
      "latest_status": "succeeded",
      "raw_output_ref": ".local/recurring-live-ingestion/google_drive",
      "source_record_count": null
    },
    "linear": {
      "age_seconds": 37,
      "connector_name": "linear-live",
      "error": "",
      "freshness_status": "fresh",
      "idempotency_status": "recorded",
      "latest_finished_at": "2026-06-09T17:20:01.119607+00:00",
      "latest_started_at": "2026-06-09T17:19:57.590075+00:00",
      "latest_status": "succeeded",
      "raw_output_ref": ".local/recurring-live-ingestion/linear",
      "source_record_count": null
    },
    "slack": {
      "age_seconds": 41,
      "connector_name": "slack-live",
      "error": "",
      "freshness_status": "fresh",
      "idempotency_status": "recorded",
      "latest_finished_at": "2026-06-09T17:19:57.580816+00:00",
      "latest_started_at": "2026-06-09T17:19:50.527363+00:00",
      "latest_status": "succeeded",
      "raw_output_ref": ".local/recurring-live-ingestion/slack",
      "source_record_count": null
    },
    "twenty": {
      "age_seconds": 48,
      "connector_name": "twenty-live",
      "error": "",
      "freshness_status": "fresh",
      "idempotency_status": "recorded",
      "latest_finished_at": "2026-06-09T17:19:50.513320+00:00",
      "latest_started_at": "2026-06-09T17:19:46.391332+00:00",
      "latest_status": "succeeded",
      "raw_output_ref": ".local/recurring-live-ingestion/twenty",
      "source_record_count": null
    }
  },
  "stale_after_minutes": 60,
  "status": "fresh"
}
```

### Post-run DB summaries
```text
timestamp=2026-06-09T19:20:38+02:00
source_records by source_system:
acceptance	1
google_drive	21
linear	222
slack	29
twenty	203
retrieval_records by source_system:
acceptance	1
google_drive	53
linear	224
slack	29
twenty	203
lifecycle/permission:
acceptance	deleted	current	1
google_drive	active	current	21
linear	active	current	222
slack	active	current	29
twenty	active	current	203
connector latest jobs:
google_drive-live	succeeded	2026-06-09T17:20:01.129182+00:00	2026-06-09T17:20:38.242794+00:00
linear-live	succeeded	2026-06-09T17:19:57.590075+00:00	2026-06-09T17:20:01.119607+00:00
slack-live	succeeded	2026-06-09T17:19:50.527363+00:00	2026-06-09T17:19:57.580816+00:00
twenty-live	succeeded	2026-06-09T17:19:46.391332+00:00	2026-06-09T17:19:50.513320+00:00
google_drive-live	failed	2026-06-09T16:36:59.267412+00:00	2026-06-09T16:37:32.476916+00:00	exit_code=1 Live Dagster import did not increase runtime DB rows: source_records_delta=0 retrieval_records_delta=53
google_drive-live	failed	2026-06-09T16:29:53.800893+00:00	2026-06-09T16:30:26.466322+00:00	exit_code=1 Live Dagster import did not increase runtime DB rows: source_records_delta=0 retrieval_records_delta=0
google_drive-live	succeeded	2026-06-09T16:29:07.089023+00:00	2026-06-09T16:29:38.230661+00:00
google_drive-live	succeeded	2026-06-09T16:26:41.039764+00:00	2026-06-09T16:27:17.641551+00:00
acceptance-fixture	succeeded	2026-06-07T07:34:58.875200+00:00	2026-06-07T07:34:58.879715+00:00
acceptance-fixture	succeeded	2026-06-07T07:23:17.267294+00:00	2026-06-07T07:23:17.270854+00:00
acceptance-fixture	succeeded	2026-06-07T02:04:11.314124+00:00	2026-06-07T02:04:11.319521+00:00
acceptance-fixture	succeeded	2026-06-07T01:59:16.951819+00:00	2026-06-07T01:59:16.954910+00:00
connector states:
acceptance-fixture	{"record_count":20,"source_ref_count":20}	2026-06-07T07:34:58.879715+00:00
google_drive-live	{"freshness_status":"fresh","idempotency_status":"recorded"}	2026-06-09T17:20:38.242794+00:00
linear-live	{"freshness_status":"fresh","idempotency_status":"recorded"}	2026-06-09T17:20:01.119607+00:00
slack-live	{"freshness_status":"fresh","idempotency_status":"recorded"}	2026-06-09T17:19:57.580816+00:00
twenty-live	{"freshness_status":"fresh","idempotency_status":"recorded"}	2026-06-09T17:19:50.513320+00:00
```

## Gate 4 — Retrieval proof
Status: IN PROGRESS

### Sampled live records from current DB
```text
-- twenty samples
twenty:person:238ad67e-5b08-43d6-964d-edd93f170a49	CODE Bouldering	[]	CODE Bouldering c_753d46f9d76ca6773a543de7bc36a632e16cb77bde7007961c388e736456aa27@group.calendar.google.com
twenty:person:29a07191-a33d-457a-a0b5-b04906c4a230	--4-8-bit Studio	[]	--4-8-bit Studio code.berlin_188f0qjk7i3s8g6bj3dtntl59ppd46gb68r34c9l64p3achp60@resource.calendar.google.com
twenty:person:115f3e64-b5c9-4b9d-9f48-174acb1b8047	--4-D2 (8)	[]	--4-D2 (8) code.berlin_1883j5g4liq5ihuehfm64pgo3o66g@resource.calendar.google.com
twenty:person:2357d596-a042-48ff-a3b6-0deaaa63599c	--4-Scissors (25)	[]	--4-Scissors (25) code.berlin_3934313230373536353639@resource.calendar.google.com
twenty:person:11434783-bb4b-4864-b11f-ac329b5e2ef6	CODE-1-B Present	[]	CODE-1-B Present c_1880c8auig7m6ie4l3p4j749vu83u@resource.calendar.google.com
-- linear samples
linear:issue:4OK-640	qontext meeting voice record + transcript. i didnt go over the auto transcript. ive cut the auido for only important parts. its also in our crm	["linear:team:09358ba1-9a6d-4550-9437-8e9daf18f93d"]	4OK-640 qontext meeting voice record + transcript. i didnt go over the auto transcript. ive cut the auido for only important parts. its also in our crm So we're
linear:issue:4OK-672	frank meeting prep	["linear:team:09358ba1-9a6d-4550-9437-8e9daf18f93d"]	4OK-672 frank meeting prep find with whom frank can meet us  | Person / role / connection | Company / headcount / industry | What they do, very simply | What we
linear:issue:4OK-385	linkedin outreach 10 inmail exact icp	["linear:team:09358ba1-9a6d-4550-9437-8e9daf18f93d"]	4OK-385 linkedin outreach 10 inmail exact icp jespers booking link: [https://fourok.fillout.com/kurzes-forschungsgesprach-zu-vertriebsprozessen](<https://fourok
linear:issue:4OK-373	Explore n8n as OpenClaw workflow automation layer	["linear:team:09358ba1-9a6d-4550-9437-8e9daf18f93d"]	4OK-373 Explore n8n as OpenClaw workflow automation layer Short take: *n8n is probably the best first bet* for OpenClaw workflow automation, with *Activepieces
linear:comment:a001cf67-a8ac-4a25-bfec-c3310798247a	Comment on 4OK-405	["linear:team:09358ba1-9a6d-4550-9437-8e9daf18f93d"]	4OK-405 Spike: evaluate Agent Vault for Baby Jules/n8n credential boundary ## Spike result: Agent Vault for Baby Jules / n8n credential boundary  **Verdict: PAR
-- slack samples
slack:channel:C0APCSD1118	#general	["slack:channel:C0APCSD1118"]	general This channel won't be used for now. Share announcements and updates about company news, upcoming events, or teammates who deserve some kudos. ⭐
slack:channel:C0AUGURHABA	#tech-support	["slack:channel:C0AUGURHABA"]	tech-support You can also just add tickets here <https://linear.app/4ok-tech/project/jules-improvements-and-bugs-fd8ae325e94d/issues>
slack:user:U0ASC2HAV7A	Jesper Morgenstern	["slack:team:T0APCSCJZC2"]	Jesper Morgenstern jesper.morgenstern jesper.morgenstern@4ok.tech
slack:channel_member:C0APCSD1118:U0APCSGCM98	U0APCSGCM98 in C0APCSD1118	["slack:channel:C0APCSD1118"]	Slack user U0APCSGCM98 is a member of channel C0APCSD1118
slack:channel_member:C0APCSD1118:U0APRPJ2UGZ	U0APRPJ2UGZ in C0APCSD1118	["slack:channel:C0APCSD1118"]	Slack user U0APRPJ2UGZ is a member of channel C0APCSD1118
-- google_drive samples
google_drive:file:1OrzMfZDwv-R_7LKUZLgfETq5FzbDCt0EShsujPMJAyw	Quick Chat (Jiayu Zhou) - 2026/05/04 16:30 CEST - Notes by Gemini	["operator"]	﻿📝 Notes May 4, 2026 Quick Chat (Jiayu Zhou) Invited jiayu.zhou@imago-images.de Simon van Laak Attachments Quick Chat (Jiayu Zhou) Meeting records Transcri
google_drive:file:1daVuh0zTiRW5KsfUpjkba177OKleM76v	buena Enterprise Architecture for Property Management Document Intelligence.md	["operator"]	# Enterprise Architecture for Property Management Document Intelligence  ## Executive recommendation  The strongest architecture for this problem is **not** an
google_drive:file:12tYJYI8VTkf2UL5knHUHpsVNkOOGlvl6Af85HNSjzLM	4ok - Sales Resource	["operator"]	﻿4ok - Sales Resource for First Customer Meetings What this document is for This document helps internal salespeople explain the Governed C
google_drive:file:12ZG0MgjYgx3qPiCSJ3ffo0bGYywmHQhiyLEWs-d0TPE	2026-05-23 Buena scalable multi-source memory and retrieval platform	["operator"]	﻿Buena scalable multi-source memory and retrieval platform Why this follow-up exists The first memo defined the privacy-safe foundation: early PII extraction,
google_drive:file:1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M	00 Drive Guide	["operator"]	﻿v 00 Start Here 00 Drive Guide 01 Team Context 01 Teams Ops 00 Shared Contact Register 01 Team Handbooks and SOPs 02 Decision Log 03 Meeting Notes 04
```

### Retrieval/search commands and outputs
```text
timestamp=2026-06-09T19:21:18+02:00
$ uv run gcb search-state 'Morgan Bros' --limit 5
{
  "query": "Morgan Bros",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [
    {
      "source_ref": "twenty:company:00061e07-9680-497a-8906-8e4644d9c078",
      "subject": "Morgan Bros",
      "date": "2026-05-07T09:25:28.977Z",
      "snippet": "Morgan Bros Morgan Bros"
    }
  ],
  "summary": "1 evidence item",
  "result_candidates": [
    {
      "source_ref": "twenty:company:00061e07-9680-497a-8906-8e4644d9c078",
      "title": "Morgan Bros",
      "snippet": "Morgan Bros Morgan Bros",
      "timestamp": "2026-05-07T09:25:28.977Z",
      "source_url": "",
      "record_type": "organization",
      "source_system": "twenty",
      "source_id": "00061e07-9680-497a-8906-8e4644d9c078",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    }
  ],
  "evidence_items": [
    {
      "source_ref": "twenty:company:00061e07-9680-497a-8906-8e4644d9c078",
      "source_url": "",
      "source_type": "Organization",
      "record_type": "organization",
      "source_system": "twenty",
      "source_id": "00061e07-9680-497a-8906-8e4644d9c078",
      "canonical_object_type": "Organization",
      "title": "Morgan Bros",
      "snippet": "Morgan Bros Morgan Bros",
      "timestamp": "2026-05-07T09:25:28.977Z",
      "updated_timestamp": "2026-05-07T09:25:28.977Z",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    }
  ],
  "primary_objects": [
    {
      "object_ref": "twenty:company:00061e07-9680-497a-8906-8e4644d9c078",
      "object_type": "Organization",
      "title": "Morgan Bros",
      "source_refs": [
        "twenty:company:00061e07-9680-497a-8906-8e4644d9c078"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    }
  ],
  "related_objects": [],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": []
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:81"
}

$ uv run gcb search-state 'Sariva' --limit 5
{
  "query": "Sariva",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [
    {
      "source_ref": "twenty:company:0005e1f3-58c7-4407-a20d-431dc675506b",
      "subject": "Sariva",
      "date": "2026-05-04T13:34:16.602Z",
      "snippet": "Sariva Sariva"
    }
  ],
  "summary": "1 evidence item",
  "result_candidates": [
    {
      "source_ref": "twenty:company:0005e1f3-58c7-4407-a20d-431dc675506b",
      "title": "Sariva",
      "snippet": "Sariva Sariva",
      "timestamp": "2026-05-04T13:34:16.602Z",
      "source_url": "",
      "record_type": "organization",
      "source_system": "twenty",
      "source_id": "0005e1f3-58c7-4407-a20d-431dc675506b",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    }
  ],
  "evidence_items": [
    {
      "source_ref": "twenty:company:0005e1f3-58c7-4407-a20d-431dc675506b",
      "source_url": "",
      "source_type": "Organization",
      "record_type": "organization",
      "source_system": "twenty",
      "source_id": "0005e1f3-58c7-4407-a20d-431dc675506b",
      "canonical_object_type": "Organization",
      "title": "Sariva",
      "snippet": "Sariva Sariva",
      "timestamp": "2026-05-04T13:34:16.602Z",
      "updated_timestamp": "2026-05-04T13:34:16.602Z",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    }
  ],
  "primary_objects": [
    {
      "object_ref": "twenty:company:0005e1f3-58c7-4407-a20d-431dc675506b",
      "object_type": "Organization",
      "title": "Sariva",
      "source_refs": [
        "twenty:company:0005e1f3-58c7-4407-a20d-431dc675506b"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    }
  ],
  "related_objects": [],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": []
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:83"
}

$ uv run gcb search-state 'Codex' --limit 5
{
  "query": "Codex",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [
    {
      "source_ref": "linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463",
      "subject": "Codex",
      "date": "2026-04-18T15:28:22.994Z",
      "snippet": "Codex Codex a4bc02c9-24f5-44c3-a1d1-03a2e3042a99@oauthapp.linear.app employee"
    }
  ],
  "summary": "1 evidence item",
  "result_candidates": [
    {
      "source_ref": "linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463",
      "title": "Codex",
      "snippet": "Codex Codex a4bc02c9-24f5-44c3-a1d1-03a2e3042a99@oauthapp.linear.app employee",
      "timestamp": "2026-04-18T15:28:22.994Z",
      "source_url": "https://linear.app/4ok-tech/profiles/codex",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "b1a18acc-66e8-4e70-aa86-f35301c4b463",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    }
  ],
  "evidence_items": [
    {
      "source_ref": "linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463",
      "source_url": "https://linear.app/4ok-tech/profiles/codex",
      "source_type": "Person",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "b1a18acc-66e8-4e70-aa86-f35301c4b463",
      "canonical_object_type": "Person",
      "title": "Codex",
      "snippet": "Codex Codex a4bc02c9-24f5-44c3-a1d1-03a2e3042a99@oauthapp.linear.app employee",
      "timestamp": "2026-04-18T15:28:22.994Z",
      "updated_timestamp": "2026-04-18T15:28:23.151Z",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    }
  ],
  "primary_objects": [
    {
      "object_ref": "linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463",
      "object_type": "Person",
      "title": "Codex",
      "source_refs": [
        "linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    }
  ],
  "related_objects": [],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": []
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:85"
}

$ uv run gcb search-state 'employee' --limit 5
{
  "query": "employee",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [
    {
      "source_ref": "google_drive:file:1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs",
      "subject": "4ok Service Proposal ",
      "date": "2026-05-08T07:47:48.596Z",
      "snippet": "... . You're stressed out. And through all of it, you have people depending on you. Employees who have been there for years. Families that rely on the stability you ..."
    },
    {
      "source_ref": "linear:user:linear-user-olivia",
      "subject": "Olivia Smith",
      "date": "",
      "snippet": "Olivia Smith Olivia Smith olivia@example.com employee"
    },
    {
      "source_ref": "linear:user:linear-user-robin-keller",
      "subject": "Robin Keller",
      "date": "",
      "snippet": "Robin Keller Robin Keller robin.keller@example.com employee"
    },
    {
      "source_ref": "linear:user:linear-user-robin-scharf",
      "subject": "Robin Scharf",
      "date": "",
      "snippet": "Robin Scharf Robin Scharf robin.scharf@example.com employee"
    },
    {
      "source_ref": "slack:user:UOLIVIA",
      "subject": "Olivia Smith",
      "date": "",
      "snippet": "Olivia Smith Olivia Smith olivia@example.com employee"
    }
  ],
  "summary": "5 evidence items",
  "result_candidates": [
    {
      "source_ref": "google_drive:file:1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs",
      "title": "4ok Service Proposal ",
      "snippet": "... . You're stressed out. And through all of it, you have people depending on you. Employees who have been there for years. Families that rely on the stability you ...",
      "timestamp": "2026-05-08T07:47:48.596Z",
      "source_url": "https://docs.google.com/document/d/1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs/edit?usp=drivesdk",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "linear:user:linear-user-olivia",
      "title": "Olivia Smith",
      "snippet": "Olivia Smith Olivia Smith olivia@example.com employee",
      "timestamp": "",
      "source_url": "",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "linear-user-olivia",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "linear:user:linear-user-robin-keller",
      "title": "Robin Keller",
      "snippet": "Robin Keller Robin Keller robin.keller@example.com employee",
      "timestamp": "",
      "source_url": "",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "linear-user-robin-keller",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "linear:user:linear-user-robin-scharf",
      "title": "Robin Scharf",
      "snippet": "Robin Scharf Robin Scharf robin.scharf@example.com employee",
      "timestamp": "",
      "source_url": "",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "linear-user-robin-scharf",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "slack:user:UOLIVIA",
      "title": "Olivia Smith",
      "snippet": "Olivia Smith Olivia Smith olivia@example.com employee",
      "timestamp": "",
      "source_url": "",
      "record_type": "person",
      "source_system": "slack",
      "source_id": "UOLIVIA",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    }
  ],
  "evidence_items": [
    {
      "source_ref": "google_drive:file:1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs",
      "source_url": "https://docs.google.com/document/d/1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs/edit?usp=drivesdk",
      "source_type": "Document",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs",
      "canonical_object_type": "Document",
      "title": "4ok Service Proposal ",
      "snippet": "... . You're stressed out. And through all of it, you have people depending on you. Employees who have been there for years. Families that rely on the stability you ...",
      "timestamp": "2026-05-08T07:47:48.596Z",
      "updated_timestamp": "2026-05-08T07:47:51.827Z",
      "linked_entities": [],
      "permission_refs": [
        "operator"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "linear:user:linear-user-olivia",
      "source_url": "",
      "source_type": "Person",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "linear-user-olivia",
      "canonical_object_type": "Person",
      "title": "Olivia Smith",
      "snippet": "Olivia Smith Olivia Smith olivia@example.com employee",
      "timestamp": "",
      "updated_timestamp": "",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "linear:user:linear-user-robin-keller",
      "source_url": "",
      "source_type": "Person",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "linear-user-robin-keller",
      "canonical_object_type": "Person",
      "title": "Robin Keller",
      "snippet": "Robin Keller Robin Keller robin.keller@example.com employee",
      "timestamp": "",
      "updated_timestamp": "",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "linear:user:linear-user-robin-scharf",
      "source_url": "",
      "source_type": "Person",
      "record_type": "person",
      "source_system": "linear",
      "source_id": "linear-user-robin-scharf",
      "canonical_object_type": "Person",
      "title": "Robin Scharf",
      "snippet": "Robin Scharf Robin Scharf robin.scharf@example.com employee",
      "timestamp": "",
      "updated_timestamp": "",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "slack:user:UOLIVIA",
      "source_url": "",
      "source_type": "Person",
      "record_type": "person",
      "source_system": "slack",
      "source_id": "UOLIVIA",
      "canonical_object_type": "Person",
      "title": "Olivia Smith",
      "snippet": "Olivia Smith Olivia Smith olivia@example.com employee",
      "timestamp": "",
      "updated_timestamp": "",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    }
  ],
  "primary_objects": [
    {
      "object_ref": "google_drive:file:1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs",
      "object_type": "Document",
      "title": "4ok Service Proposal ",
      "source_refs": [
        "google_drive:file:1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "linear:user:linear-user-olivia",
      "object_type": "Person",
      "title": "Olivia Smith",
      "source_refs": [
        "linear:user:linear-user-olivia"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "linear:user:linear-user-robin-keller",
      "object_type": "Person",
      "title": "Robin Keller",
      "source_refs": [
        "linear:user:linear-user-robin-keller"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "linear:user:linear-user-robin-scharf",
      "object_type": "Person",
      "title": "Robin Scharf",
      "source_refs": [
        "linear:user:linear-user-robin-scharf"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "slack:user:UOLIVIA",
      "object_type": "Person",
      "title": "Olivia Smith",
      "source_refs": [
        "slack:user:UOLIVIA"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    }
  ],
  "related_objects": [],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": []
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:87"
}

$ uv run gcb search-state 'temp-crm' --limit 5
{
  "query": "temp-crm",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [],
  "summary": "0 evidence items",
  "result_candidates": [],
  "evidence_items": [],
  "primary_objects": [],
  "related_objects": [],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": []
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:89"
}

$ uv run gcb search-state 'temp-crm' --role slack:channel:C0AU5K1B940 --limit 5
{
  "query": "temp-crm",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [
    {
      "source_ref": "slack:channel:C0AU5K1B940",
      "subject": "#temp-crm",
      "date": "1776333841",
      "snippet": "#temp-crm temp-crm"
    }
  ],
  "summary": "1 evidence item",
  "result_candidates": [
    {
      "source_ref": "slack:channel:C0AU5K1B940",
      "title": "#temp-crm",
      "snippet": "#temp-crm temp-crm",
      "timestamp": "1776333841",
      "source_url": "",
      "record_type": "work_item",
      "source_system": "slack",
      "source_id": "C0AU5K1B940",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    }
  ],
  "evidence_items": [
    {
      "source_ref": "slack:channel:C0AU5K1B940",
      "source_url": "",
      "source_type": "WorkItem",
      "record_type": "work_item",
      "source_system": "slack",
      "source_id": "C0AU5K1B940",
      "canonical_object_type": "WorkItem",
      "title": "#temp-crm",
      "snippet": "#temp-crm temp-crm",
      "timestamp": "1776333841",
      "updated_timestamp": "",
      "linked_entities": [],
      "permission_refs": [
        "slack:channel:C0AU5K1B940"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    }
  ],
  "primary_objects": [
    {
      "object_ref": "slack:channel:C0AU5K1B940",
      "object_type": "WorkItem",
      "title": "#temp-crm",
      "source_refs": [
        "slack:channel:C0AU5K1B940"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    }
  ],
  "related_objects": [
    {
      "object_ref": "slack:channel_member:C0AU5K1B940:U0APCSGCM98",
      "object_type": "Relationship",
      "title": "U0APCSGCM98 in C0AU5K1B940",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0AU5K1B940",
        "slack:channel_member:C0AU5K1B940:U0APCSGCM98"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0APCSGCM98 in C0AU5K1B940"
    },
    {
      "object_ref": "slack:channel_member:C0AU5K1B940:U0APRPJ2UGZ",
      "object_type": "Relationship",
      "title": "U0APRPJ2UGZ in C0AU5K1B940",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0AU5K1B940",
        "slack:channel_member:C0AU5K1B940:U0APRPJ2UGZ"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0APRPJ2UGZ in C0AU5K1B940"
    },
    {
      "object_ref": "slack:channel_member:C0AU5K1B940:U0AQQAV8U6Q",
      "object_type": "Relationship",
      "title": "U0AQQAV8U6Q in C0AU5K1B940",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0AU5K1B940",
        "slack:channel_member:C0AU5K1B940:U0AQQAV8U6Q"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0AQQAV8U6Q in C0AU5K1B940"
    },
    {
      "object_ref": "slack:channel_member:C0AU5K1B940:U0AREC034J1",
      "object_type": "Relationship",
      "title": "U0AREC034J1 in C0AU5K1B940",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0AU5K1B940",
        "slack:channel_member:C0AU5K1B940:U0AREC034J1"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0AREC034J1 in C0AU5K1B940"
    },
    {
      "object_ref": "slack:channel_member:C0AU5K1B940:U0ASC2HAV7A",
      "object_type": "Relationship",
      "title": "U0ASC2HAV7A in C0AU5K1B940",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0AU5K1B940",
        "slack:channel_member:C0AU5K1B940:U0ASC2HAV7A"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0ASC2HAV7A in C0AU5K1B940"
    }
  ],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": [
      {
        "object_ref": "slack:channel_member:C0AU5K1B940:U0APCSGCM98",
        "object_type": "Relationship",
        "title": "U0APCSGCM98 in C0AU5K1B940",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0AU5K1B940",
          "slack:channel_member:C0AU5K1B940:U0APCSGCM98"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0APCSGCM98 in C0AU5K1B940"
      },
      {
        "object_ref": "slack:channel_member:C0AU5K1B940:U0APRPJ2UGZ",
        "object_type": "Relationship",
        "title": "U0APRPJ2UGZ in C0AU5K1B940",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0AU5K1B940",
          "slack:channel_member:C0AU5K1B940:U0APRPJ2UGZ"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0APRPJ2UGZ in C0AU5K1B940"
      },
      {
        "object_ref": "slack:channel_member:C0AU5K1B940:U0AQQAV8U6Q",
        "object_type": "Relationship",
        "title": "U0AQQAV8U6Q in C0AU5K1B940",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0AU5K1B940",
          "slack:channel_member:C0AU5K1B940:U0AQQAV8U6Q"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0AQQAV8U6Q in C0AU5K1B940"
      },
      {
        "object_ref": "slack:channel_member:C0AU5K1B940:U0AREC034J1",
        "object_type": "Relationship",
        "title": "U0AREC034J1 in C0AU5K1B940",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0AU5K1B940",
          "slack:channel_member:C0AU5K1B940:U0AREC034J1"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0AREC034J1 in C0AU5K1B940"
      },
      {
        "object_ref": "slack:channel_member:C0AU5K1B940:U0ASC2HAV7A",
        "object_type": "Relationship",
        "title": "U0ASC2HAV7A in C0AU5K1B940",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0AU5K1B940",
          "slack:channel_member:C0AU5K1B940:U0ASC2HAV7A"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0ASC2HAV7A in C0AU5K1B940"
      }
    ]
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:90"
}

$ uv run gcb search-state 'general' --role slack:channel:C0APCSD1118 --limit 5
{
  "query": "general",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [
    {
      "source_ref": "slack:channel:C0APCSD1118",
      "subject": "#general",
      "date": "1774634807",
      "snippet": "#general general This channel won't be used for now. Share announcements and updates about company news, upcoming events, or teammates who deserve some kudos. \u2b50"
    },
    {
      "source_ref": "google_drive:file:1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE",
      "subject": "Information Sheet: Understanding How Sales Teams Work",
      "date": "2026-04-15T07:35:04.326Z",
      "snippet": "... nagers get visibility into team activity and deal progress We are interested in general workflows, team habits, and common challenges in manufacturing sales, es ..."
    },
    {
      "source_ref": "google_drive:file:1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M",
      "subject": "00 Drive Guide",
      "date": "2026-04-13T15:33:38.487Z",
      "snippet": "... PRDs This folder stores product requirement documents. PRDs are used to define general product directions that may become important for the company. They shoul ..."
    },
    {
      "source_ref": "twenty:person:1c4a4495-1afa-41dd-b90f-f887d12c2124",
      "subject": "F&M Kontakt",
      "date": "2026-05-04T12:43:28.882Z",
      "snippet": "F&M Kontakt F&M Kontakt General contact info@fm-maschinenbau.de"
    },
    {
      "source_ref": "twenty:person:2634a346-9f8d-40ed-a6dd-d6f52c8223f5",
      "subject": "Martin & Schwender Kontakt",
      "date": "2026-05-04T12:43:28.882Z",
      "snippet": "Martin & Schwender Kontakt Martin & Schwender Kontakt General contact info@martin-klima.de"
    }
  ],
  "summary": "5 evidence items",
  "result_candidates": [
    {
      "source_ref": "slack:channel:C0APCSD1118",
      "title": "#general",
      "snippet": "#general general This channel won't be used for now. Share announcements and updates about company news, upcoming events, or teammates who deserve some kudos. \u2b50",
      "timestamp": "1774634807",
      "source_url": "",
      "record_type": "work_item",
      "source_system": "slack",
      "source_id": "C0APCSD1118",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "google_drive:file:1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE",
      "title": "Information Sheet: Understanding How Sales Teams Work",
      "snippet": "... nagers get visibility into team activity and deal progress We are interested in general workflows, team habits, and common challenges in manufacturing sales, es ...",
      "timestamp": "2026-04-15T07:35:04.326Z",
      "source_url": "https://docs.google.com/document/d/1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE/edit?usp=drivesdk",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "google_drive:file:1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M",
      "title": "00 Drive Guide",
      "snippet": "... PRDs This folder stores product requirement documents. PRDs are used to define general product directions that may become important for the company. They shoul ...",
      "timestamp": "2026-04-13T15:33:38.487Z",
      "source_url": "https://docs.google.com/document/d/1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M/edit?usp=drivesdk",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "twenty:person:1c4a4495-1afa-41dd-b90f-f887d12c2124",
      "title": "F&M Kontakt",
      "snippet": "F&M Kontakt F&M Kontakt General contact info@fm-maschinenbau.de",
      "timestamp": "2026-05-04T12:43:28.882Z",
      "source_url": "",
      "record_type": "person",
      "source_system": "twenty",
      "source_id": "1c4a4495-1afa-41dd-b90f-f887d12c2124",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "twenty:person:2634a346-9f8d-40ed-a6dd-d6f52c8223f5",
      "title": "Martin & Schwender Kontakt",
      "snippet": "Martin & Schwender Kontakt Martin & Schwender Kontakt General contact info@martin-klima.de",
      "timestamp": "2026-05-04T12:43:28.882Z",
      "source_url": "",
      "record_type": "person",
      "source_system": "twenty",
      "source_id": "2634a346-9f8d-40ed-a6dd-d6f52c8223f5",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    }
  ],
  "evidence_items": [
    {
      "source_ref": "slack:channel:C0APCSD1118",
      "source_url": "",
      "source_type": "WorkItem",
      "record_type": "work_item",
      "source_system": "slack",
      "source_id": "C0APCSD1118",
      "canonical_object_type": "WorkItem",
      "title": "#general",
      "snippet": "#general general This channel won't be used for now. Share announcements and updates about company news, upcoming events, or teammates who deserve some kudos. \u2b50",
      "timestamp": "1774634807",
      "updated_timestamp": "",
      "linked_entities": [],
      "permission_refs": [
        "slack:channel:C0APCSD1118"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "google_drive:file:1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE",
      "source_url": "https://docs.google.com/document/d/1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE/edit?usp=drivesdk",
      "source_type": "Document",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE",
      "canonical_object_type": "Document",
      "title": "Information Sheet: Understanding How Sales Teams Work",
      "snippet": "... nagers get visibility into team activity and deal progress We are interested in general workflows, team habits, and common challenges in manufacturing sales, es ...",
      "timestamp": "2026-04-15T07:35:04.326Z",
      "updated_timestamp": "2026-05-13T13:54:53.881Z",
      "linked_entities": [],
      "permission_refs": [
        "operator"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "google_drive:file:1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M",
      "source_url": "https://docs.google.com/document/d/1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M/edit?usp=drivesdk",
      "source_type": "Document",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M",
      "canonical_object_type": "Document",
      "title": "00 Drive Guide",
      "snippet": "... PRDs This folder stores product requirement documents. PRDs are used to define general product directions that may become important for the company. They shoul ...",
      "timestamp": "2026-04-13T15:33:38.487Z",
      "updated_timestamp": "2026-05-21T15:13:48.123Z",
      "linked_entities": [],
      "permission_refs": [
        "operator"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "twenty:person:1c4a4495-1afa-41dd-b90f-f887d12c2124",
      "source_url": "",
      "source_type": "Person",
      "record_type": "person",
      "source_system": "twenty",
      "source_id": "1c4a4495-1afa-41dd-b90f-f887d12c2124",
      "canonical_object_type": "Person",
      "title": "F&M Kontakt",
      "snippet": "F&M Kontakt F&M Kontakt General contact info@fm-maschinenbau.de",
      "timestamp": "2026-05-04T12:43:28.882Z",
      "updated_timestamp": "2026-05-04T12:43:32.109Z",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "twenty:person:2634a346-9f8d-40ed-a6dd-d6f52c8223f5",
      "source_url": "",
      "source_type": "Person",
      "record_type": "person",
      "source_system": "twenty",
      "source_id": "2634a346-9f8d-40ed-a6dd-d6f52c8223f5",
      "canonical_object_type": "Person",
      "title": "Martin & Schwender Kontakt",
      "snippet": "Martin & Schwender Kontakt Martin & Schwender Kontakt General contact info@martin-klima.de",
      "timestamp": "2026-05-04T12:43:28.882Z",
      "updated_timestamp": "2026-05-04T12:43:32.071Z",
      "linked_entities": [],
      "permission_refs": [],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    }
  ],
  "primary_objects": [
    {
      "object_ref": "slack:channel:C0APCSD1118",
      "object_type": "WorkItem",
      "title": "#general",
      "source_refs": [
        "slack:channel:C0APCSD1118"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "google_drive:file:1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE",
      "object_type": "Document",
      "title": "Information Sheet: Understanding How Sales Teams Work",
      "source_refs": [
        "google_drive:file:1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "google_drive:file:1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M",
      "object_type": "Document",
      "title": "00 Drive Guide",
      "source_refs": [
        "google_drive:file:1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "twenty:person:1c4a4495-1afa-41dd-b90f-f887d12c2124",
      "object_type": "Person",
      "title": "F&M Kontakt",
      "source_refs": [
        "twenty:person:1c4a4495-1afa-41dd-b90f-f887d12c2124"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "twenty:person:2634a346-9f8d-40ed-a6dd-d6f52c8223f5",
      "object_type": "Person",
      "title": "Martin & Schwender Kontakt",
      "source_refs": [
        "twenty:person:2634a346-9f8d-40ed-a6dd-d6f52c8223f5"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    }
  ],
  "related_objects": [
    {
      "object_ref": "slack:channel_member:C0APCSD1118:U0APCSGCM98",
      "object_type": "Relationship",
      "title": "U0APCSGCM98 in C0APCSD1118",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0APCSD1118",
        "slack:channel_member:C0APCSD1118:U0APCSGCM98"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0APCSGCM98 in C0APCSD1118"
    },
    {
      "object_ref": "slack:channel_member:C0APCSD1118:U0APRPJ2UGZ",
      "object_type": "Relationship",
      "title": "U0APRPJ2UGZ in C0APCSD1118",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0APCSD1118",
        "slack:channel_member:C0APCSD1118:U0APRPJ2UGZ"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0APRPJ2UGZ in C0APCSD1118"
    },
    {
      "object_ref": "slack:channel_member:C0APCSD1118:U0AREC034J1",
      "object_type": "Relationship",
      "title": "U0AREC034J1 in C0APCSD1118",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0APCSD1118",
        "slack:channel_member:C0APCSD1118:U0AREC034J1"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0AREC034J1 in C0APCSD1118"
    },
    {
      "object_ref": "slack:channel_member:C0APCSD1118:U0ASC2HAV7A",
      "object_type": "Relationship",
      "title": "U0ASC2HAV7A in C0APCSD1118",
      "relationship_to_primary": "same thread",
      "relationship_source_refs": [
        "slack:channel:C0APCSD1118",
        "slack:channel_member:C0APCSD1118:U0ASC2HAV7A"
      ],
      "confidence": 0.9,
      "follow_up_hint": "Ask about U0ASC2HAV7A in C0APCSD1118"
    }
  ],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": [
      {
        "object_ref": "slack:channel_member:C0APCSD1118:U0APCSGCM98",
        "object_type": "Relationship",
        "title": "U0APCSGCM98 in C0APCSD1118",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0APCSD1118",
          "slack:channel_member:C0APCSD1118:U0APCSGCM98"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0APCSGCM98 in C0APCSD1118"
      },
      {
        "object_ref": "slack:channel_member:C0APCSD1118:U0APRPJ2UGZ",
        "object_type": "Relationship",
        "title": "U0APRPJ2UGZ in C0APCSD1118",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0APCSD1118",
          "slack:channel_member:C0APCSD1118:U0APRPJ2UGZ"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0APRPJ2UGZ in C0APCSD1118"
      },
      {
        "object_ref": "slack:channel_member:C0APCSD1118:U0AREC034J1",
        "object_type": "Relationship",
        "title": "U0AREC034J1 in C0APCSD1118",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0APCSD1118",
          "slack:channel_member:C0APCSD1118:U0AREC034J1"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0AREC034J1 in C0APCSD1118"
      },
      {
        "object_ref": "slack:channel_member:C0APCSD1118:U0ASC2HAV7A",
        "object_type": "Relationship",
        "title": "U0ASC2HAV7A in C0APCSD1118",
        "relationship_to_primary": "same thread",
        "relationship_source_refs": [
          "slack:channel:C0APCSD1118",
          "slack:channel_member:C0APCSD1118:U0ASC2HAV7A"
        ],
        "confidence": 0.9,
        "follow_up_hint": "Ask about U0ASC2HAV7A in C0APCSD1118"
      }
    ]
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:92"
}

$ uv run gcb search-state 'Buena Architecture Overview' --limit 5
{
  "query": "Buena Architecture Overview",
  "load": {
    "loaded": 0,
    "source": "existing_state"
  },
  "results": [
    {
      "source_ref": "google_drive:file:1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA",
      "subject": "Buena Progress Update",
      "date": "2026-05-24T13:43:00.284Z",
      "snippet": "Buena Progress Update \ufeff# Buena Document Classification: Architecture Overview This document summarizes the current prototype architecture at a high level. It is ..."
    },
    {
      "source_ref": "google_drive:file:19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI",
      "subject": "Buena Progress Update tmp semantic test",
      "date": "2026-06-05T14:55:04.124Z",
      "snippet": "Buena Progress Update tmp semantic test \ufeffBuena Document Classification: Architecture Overview This document summarizes the current prototype architecture at a h ..."
    },
    {
      "source_ref": "google_drive:file:1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM",
      "subject": "buena-progress-update-backup-before-reset",
      "date": "2026-06-05T15:03:29.085Z",
      "snippet": "buena-progress-update-backup-before-reset \ufeff# Buena Document Classification: Architecture Overview This document summarizes the current prototype architecture at ..."
    }
  ],
  "summary": "3 evidence items",
  "result_candidates": [
    {
      "source_ref": "google_drive:file:1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA",
      "title": "Buena Progress Update",
      "snippet": "Buena Progress Update \ufeff# Buena Document Classification: Architecture Overview This document summarizes the current prototype architecture at a high level. It is ...",
      "timestamp": "2026-05-24T13:43:00.284Z",
      "source_url": "https://docs.google.com/document/d/1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA/edit?usp=drivesdk",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "google_drive:file:19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI",
      "title": "Buena Progress Update tmp semantic test",
      "snippet": "Buena Progress Update tmp semantic test \ufeffBuena Document Classification: Architecture Overview This document summarizes the current prototype architecture at a h ...",
      "timestamp": "2026-06-05T14:55:04.124Z",
      "source_url": "https://docs.google.com/document/d/19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI/edit?usp=drivesdk",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    },
    {
      "source_ref": "google_drive:file:1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM",
      "title": "buena-progress-update-backup-before-reset",
      "snippet": "buena-progress-update-backup-before-reset \ufeff# Buena Document Classification: Architecture Overview This document summarizes the current prototype architecture at ...",
      "timestamp": "2026-06-05T15:03:29.085Z",
      "source_url": "https://docs.google.com/document/d/1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM/edit?usp=drivesdk",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM",
      "ranking_reason": "keyword match in permission-filtered retrieval unit",
      "score": null
    }
  ],
  "evidence_items": [
    {
      "source_ref": "google_drive:file:1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA",
      "source_url": "https://docs.google.com/document/d/1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA/edit?usp=drivesdk",
      "source_type": "Document",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA",
      "canonical_object_type": "Document",
      "title": "Buena Progress Update",
      "snippet": "Buena Progress Update \ufeff# Buena Document Classification: Architecture Overview This document summarizes the current prototype architecture at a high level. It is ...",
      "timestamp": "2026-05-24T13:43:00.284Z",
      "updated_timestamp": "2026-06-05T15:03:37.549Z",
      "linked_entities": [],
      "permission_refs": [
        "operator"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "google_drive:file:19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI",
      "source_url": "https://docs.google.com/document/d/19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI/edit?usp=drivesdk",
      "source_type": "Document",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI",
      "canonical_object_type": "Document",
      "title": "Buena Progress Update tmp semantic test",
      "snippet": "Buena Progress Update tmp semantic test \ufeffBuena Document Classification: Architecture Overview This document summarizes the current prototype architecture at a h ...",
      "timestamp": "2026-06-05T14:55:04.124Z",
      "updated_timestamp": "2026-06-05T14:55:04.124Z",
      "linked_entities": [],
      "permission_refs": [
        "operator"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    },
    {
      "source_ref": "google_drive:file:1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM",
      "source_url": "https://docs.google.com/document/d/1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM/edit?usp=drivesdk",
      "source_type": "Document",
      "record_type": "document",
      "source_system": "google_drive",
      "source_id": "1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM",
      "canonical_object_type": "Document",
      "title": "buena-progress-update-backup-before-reset",
      "snippet": "buena-progress-update-backup-before-reset \ufeff# Buena Document Classification: Architecture Overview This document summarizes the current prototype architecture at ...",
      "timestamp": "2026-06-05T15:03:29.085Z",
      "updated_timestamp": "2026-06-05T15:03:29.085Z",
      "linked_entities": [],
      "permission_refs": [
        "operator"
      ],
      "score": null,
      "why_included": "matched permission-filtered retrieval text"
    }
  ],
  "primary_objects": [
    {
      "object_ref": "google_drive:file:1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA",
      "object_type": "Document",
      "title": "Buena Progress Update",
      "source_refs": [
        "google_drive:file:1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "google_drive:file:19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI",
      "object_type": "Document",
      "title": "Buena Progress Update tmp semantic test",
      "source_refs": [
        "google_drive:file:19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    },
    {
      "object_ref": "google_drive:file:1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM",
      "object_type": "Document",
      "title": "buena-progress-update-backup-before-reset",
      "source_refs": [
        "google_drive:file:1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM"
      ],
      "why_primary": "matched evidence source",
      "confidence": 1.0
    }
  ],
  "related_objects": [],
  "related_object_groups": {
    "people": [],
    "organizations": [],
    "work_items": [],
    "documents": [],
    "threads": []
  },
  "entities": [],
  "unresolved_candidates": [],
  "limitations": [
    "related object expansion is limited to source-backed entity links and threads"
  ],
  "audit_ref": "audit:search:94"
}

```

### Retrieval proof summary matrix
```text
twenty-1	PASS=True	expect=find:twenty:company:00061e07-9680-497a-8906-8e4644d9c078	summary=1 evidence item	refs=['twenty:company:00061e07-9680-497a-8906-8e4644d9c078']	cmd=uv run gcb search-state 'Morgan Bros' --limit 5
twenty-2	PASS=True	expect=find:twenty:company:0005e1f3-58c7-4407-a20d-431dc675506b	summary=1 evidence item	refs=['twenty:company:0005e1f3-58c7-4407-a20d-431dc675506b']	cmd=uv run gcb search-state Sariva --limit 5
linear-1	PASS=True	expect=find:linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463	summary=1 evidence item	refs=['linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463']	cmd=uv run gcb search-state Codex --limit 5
linear-2	PASS=True	expect=find:linear:	summary=5 evidence items	refs=['google_drive:file:1ywgCeaxU4HgJNCKAnFYXjeabvXOYDX7Y9nNdWkKGcJs', 'linear:user:linear-user-olivia', 'linear:user:linear-user-robin-keller', 'linear:user:linear-user-robin-scharf', 'slack:user:UOLIVIA']	cmd=uv run gcb search-state employee --limit 5
slack-denied	PASS=True	expect=deny:slack:channel:C0AU5K1B940	summary=0 evidence items	refs=[]	cmd=uv run gcb search-state temp-crm --limit 5
slack-allowed-1	PASS=True	expect=find:slack:channel:C0AU5K1B940	summary=1 evidence item	refs=['slack:channel:C0AU5K1B940']	cmd=uv run gcb search-state temp-crm --limit 5 --role slack:channel:C0AU5K1B940
slack-allowed-2	PASS=True	expect=find:slack:channel:C0APCSD1118	summary=5 evidence items	refs=['slack:channel:C0APCSD1118', 'google_drive:file:1FyvjFIIlXZiKLGn3ce8fypFzn-gDnf8Av-IQdXYfBYE', 'google_drive:file:1npxJYLu8q_lzONlgyKG5GAzCbKQdglDGmpxrqU4iR9M', 'twenty:person:1c4a4495-1afa-41dd-b90f-f887d12c2124', 'twenty:person:2634a346-9f8d-40ed-a6dd-d6f52c8223f5']	cmd=uv run gcb search-state general --limit 5 --role slack:channel:C0APCSD1118
google-1	PASS=True	expect=find:google_drive:file:	summary=3 evidence items	refs=['google_drive:file:1I0vBv-kBrPt0Gv6CD3cdpw_cZ6L5KEhHvina3OC9HGA', 'google_drive:file:19WDGlrud5NYo2P9MXhFAD0RoZk9ZVlG3HOL4wlQ0kZI', 'google_drive:file:1bqos9wvvKLRbGTyMnQoLeANfxI-tYdtLEVjSqwOctjM']	cmd=uv run gcb search-state 'Buena Architecture Overview' --limit 5
google-2	PASS=True	expect=find:google_drive:file:12tYJYI8VTkf2UL5knHUHpsVNkOOGlvl6Af85HNSjzLM	summary=3 evidence items	refs=['google_drive:file:12tYJYI8VTkf2UL5knHUHpsVNkOOGlvl6Af85HNSjzLM', 'google_drive:file:12tYJYI8VTkf2UL5knHUHpsVNkOOGlvl6Af85HNSjzLM', 'google_drive:file:12tYJYI8VTkf2UL5knHUHpsVNkOOGlvl6Af85HNSjzLM']	cmd=uv run gcb search-state '4ok Sales Resource' --limit 5
```

## Gate 3 — Verification tooling proof
Status: IN PROGRESS

### Regression tests for idempotent live DB verifier
```text
timestamp=2026-06-09T19:24:26+02:00
..                                                                       [100%]
2 passed in 0.55s
```

### Live idempotent verifier command after fix
```text
{
  "sources": [
    {
      "artifact_dir": ".local/recurring-live-ingestion/google_drive",
      "connector_name": "google_drive-live",
      "job_id": "3ff0e1fa-98d0-413c-aaf7-08807d5d95a6",
      "record_count": null,
      "retrieval_record_count": null,
      "source": "google_drive",
      "source_record_count": null,
      "status": "succeeded"
    }
  ],
  "status": "succeeded"
}
```

### Raw landed JSONL counts by live source
```text
timestamp=2026-06-09T19:25:21+02:00
twenty	total_jsonl_lines=200	raw/twenty_live/twenty_companies.jsonl=100; raw/twenty_live/twenty_people.jsonl=100
slack	total_jsonl_lines=26	raw/slack_live/channel_members.jsonl=14; raw/slack_live/channels.jsonl=3; raw/slack_live/users.jsonl=9
linear	total_jsonl_lines=207	raw/linear_live/linear_comments.jsonl=100; raw/linear_live/linear_issues.jsonl=100; raw/linear_live/linear_users.jsonl=7
google_drive	total_jsonl_lines=21	raw/google_drive_live/google_drive_files.jsonl=21
```

### Automated regression/test suite after verifier fix
```text
timestamp=2026-06-09T19:25:52+02:00
uv run pytest tests/runtime/test_dagster_pipeline.py tests/etl/extract/test_google_drive_connectors.py tests/etl/extract/test_google_drive_tap.py tests/etl/extract/test_connectors_ingest.py -q
51 passed in 0.73s
git diff --check: passed
```

## Gate 5 — Deployment/infra proof
Status: IN PROGRESS

### Infra repository and GitHub Actions evidence
```text
timestamp=2026-06-09T19:25:52+02:00
infra git status:
## main...origin/main

recent infra commits:
9b010dd (HEAD -> main, origin/main, origin/HEAD) Clarify OpenViking read level guidance
362d53e Preserve prod Slack DM routing on promotion
f48d5b2 Restore 4ok Jules model fallback
d0b7c57 Keep prod Slack DMs out of assistant threads
ce40e13 Retry Infisical CLI download in dev deploy workflow
77e5f3a Mount Codex auth bootstrap helper in gateway runtime
094af3c Allow prod gateway runtime secret read actions
c542a2a Stage Codex bootstrap helper in runtime bundle

recent GitHub Actions runs (infra repo):
completed	skipped	hermes-workflow-failure-notify	hermes-workflow-failure-notify	main	workflow_run	27198125552	1s	2026-06-09T09:51:20Z
completed	skipped	hermes-workflow-failure-notify	hermes-workflow-failure-notify	main	workflow_run	27197805928	1s	2026-06-09T09:45:16Z
completed	skipped	hermes-workflow-failure-notify	hermes-workflow-failure-notify	main	workflow_run	27197700295	2s	2026-06-09T09:43:19Z
completed	success	Clarify OpenViking read level guidance	4ok-openclaw-dev-image	main	push	27197688611	13m51s	2026-06-09T09:43:06Z
completed	success	Clarify OpenViking read level guidance	dev-customer-gateway-4ok-runtime-deploy	main	push	27197688406	11s	2026-06-09T09:43:06Z
completed	success	Clarify OpenViking read level guidance	devex-validation	main	push	27197688393	22s	2026-06-09T09:43:06Z
completed	success	Clarify OpenViking read level guidance	prod-customer-gateway-4ok-runtime-validate	main	push	27197688391	2m6s	2026-06-09T09:43:06Z
completed	success	Clarify OpenViking read level guidance	promote-4ok-dev-to-prod	main	push	27197688389	17s	2026-06-09T09:43:06Z
completed	success	Clarify OpenViking read level guidance	4ok-openclaw-image	main	push	27197688382	8m8s	2026-06-09T09:43:06Z
completed	skipped	hermes-workflow-failure-notify	hermes-workflow-failure-notify	main	workflow_run	27132485706	1s	2026-06-08T10:47:01Z
completed	skipped	hermes-workflow-failure-notify	hermes-workflow-failure-notify	main	workflow_run	27132390337	1s	2026-06-08T10:45:07Z
completed	success	prod-customer-gateway-4ok-runtime-deploy	prod-customer-gateway-4ok-runtime-deploy	main	workflow_dispatch	27132037285	7m5s	2026-06-08T10:38:00Z
completed	skipped	hermes-workflow-failure-notify	hermes-workflow-failure-notify	main	workflow_run	27132022070	1s	2026-06-08T10:37:40Z
completed	success	Preserve prod Slack DM routing on promotion	devex-validation	main	push	27132008460	20s	2026-06-08T10:37:24Z
completed	success	Preserve prod Slack DM routing on promotion	promote-4ok-dev-to-prod	main	push	27132008425	15s	2026-06-08T10:37:24Z
completed	success	Preserve prod Slack DM routing on promotion	prod-customer-gateway-4ok-runtime-validate	main	push	27132008416	14s	2026-06-08T10:37:24Z
completed	success	hermes-workflow-failure-notify	hermes-workflow-failure-notify	main	workflow_run	27131912558	10s	2026-06-08T10:35:24Z
completed	failure	Restore 4ok Jules model fallback	promote-4ok-dev-to-prod	main	push	27131899326	18s	2026-06-08T10:35:09Z
completed	failure	Restore 4ok Jules model fallback	prod-customer-gateway-4ok-runtime-validate	main	push	27131899308	12s	2026-06-08T10:35:09Z
completed	success	Restore 4ok Jules model fallback	devex-validation	main	push	27131899243	21s	2026-06-08T10:35:09Z
```

### 4ok runtime lineage trace
```text
timestamp=2026-06-09T19:26:13+02:00
usage: trace-4ok-runtime-lineage.py [-h] --environment {dev,prod} --repo REPO
                                    [--repo-root REPO_ROOT]
                                    [--build-run-id BUILD_RUN_ID]
                                    [--image-digest IMAGE_DIGEST]
                                    [--ssh-live-check] [--ssh-host SSH_HOST]
                                    [--ssh-user SSH_USER]

Trace 4ok runtime source/image/deploy lineage.

options:
  -h, --help            show this help message and exit
  --environment {dev,prod}
  --repo REPO
  --repo-root REPO_ROOT
  --build-run-id BUILD_RUN_ID
  --image-digest IMAGE_DIGEST
  --ssh-live-check
  --ssh-host SSH_HOST
  --ssh-user SSH_USER
--- trace dev ---
--- trace prod ---
```

### Corrected 4ok runtime lineage trace
```text
timestamp=2026-06-09T19:26:38+02:00
dev:
prod:
```

## Gate status summary as of finalization attempt
```text
timestamp=2026-06-09T19:27:15+02:00
Gate 1 baseline/runtime health: PASS — GCB runtime DB reachable, relevant containers healthy, GCB/infra git state recorded.
Gate 2 live ingestion: PASS — run-live-ingestion --source all succeeded; connector states fresh; current rows/retrieval/lifecycle/permission/raw counts recorded.
Gate 3 verification tooling: PASS — verifier accepts idempotent current rows, rejects decreases; targeted regression tests passed; google_drive --verify-live-db succeeded.
Gate 4 retrieval proof: PASS — two Twenty, two Linear, Slack denied+allowed role behavior, and two Google Drive searches passed in summary matrix.
Gate 5 deployment/infra proof: NOT COMPLETE — infra repo is clean and recent existing workflows are green, but no new infra deployment change was made/verified for this GCB goal; runtime lineage script could not complete via gh api workflow lookup. Existing green CI predates this GCB verifier commit and does not prove a new deployment.
Gate 6 final report: NOT COMPLETE — report committed in GCB commit below, but deployment gate remains unverified.
GCB evidence/verifier commit: 9a5e091 fix: accept idempotent live DB verification
```

## Scope update — deployment intentionally out of scope
```text
timestamp=2026-06-09T19:31:10+02:00
User confirmed deployment can stay out of scope for now.
Current local/live scope: live ingestion + runtime DB rows + permissions/lifecycle + retrieval/search for Twenty, Slack, Linear, and Google Drive.
Local/live status: COMPLETE for the evidence captured above.
Deployment status: OUT OF SCOPE, not a blocker for the current local/retrieval milestone.
```
