# Dreaming memory plugin — benchmark results

Run `20261111-180504` · model `gpt-6.1-sol` · Hermes Agent v0.23.1+1921.g4ed1425 (2026.9.24) · stable · local 4ed14253ea7b

24 project-log sessions, then 20 questions. Every session and every question is a separate, brand-new Hermes session (`hermes -z`), so answers can only come from memory. All arms use the same toolsets (`memory,session_search`); the only difference is `memory.provider`.

| Arm | Setup |
|---|---|
| **base** | Hermes built-in memory |
| **raw** | dreaming plugin, no dream |
| **dream** | dreaming plugin + dream pass |

## Accuracy

| Question group | base | raw | dream |
|---|---|---|---|
| recall | 6/6 | 6/6 | 6/6 |
| multi-hop | 5/5 | 5/5 | 5/5 |
| superseded | 5/5 | 5/5 | 5/5 |
| corrupted-note ¹ | 2/4 | 4/4 | 4/4 |
| **All questions** | 18/20 (90%) | 20/20 (100%) | 20/20 (100%) |

¹ Before the questions (and before the dream pass), four true values were replaced with wrong ones inside each arm's own notes: built-in `MEMORY.md` for `base`, the plugin's `notes/` for `raw` and `dream`. Transcripts and session history were left intact. Occurrences replaced per arm:

| Fact damaged | base | raw | dream |
|---|---|---|---|
| standup time 9:40 → 10:15 | 1 | 1 | 1 |
| retention 400 → 180 days | 0 | 1 | 1 |
| cert alarm 21 → 14 days | 0 | 1 | 1 |
| prod region eu-north-2 → eu-west-4 | 1 | 1 | 1 |

## Cost of answering a question (mean per question)

| | base | raw | dream |
|---|---|---|---|
| Model calls | 1.8 | 1.5 | 1.1 |
| Input tokens | 7,758 | 7,292 | 4,805 |
| Output tokens | 48 | 35 | 18 |
| Auxiliary model calls | 0.0 | 0.0 | 0.0 |
| Seconds | 7.2 | 6.7 | 4.2 |

## Cost of remembering

| | base | raw | dream |
|---|---|---|---|
| Model calls over all sessions | 46 | 48 | 48 |
| Input tokens over all sessions | 163,506 | 201,387 | 202,194 |
| Seconds over all sessions | 251 | 208 | 205 |
| Dream pass | — | — | 3 calls, 68.1s |

## What each arm had in memory when the questions started

| | base | raw | dream |
|---|---|---|---|
| builtin MEMORY.md | 1,917 | 0 | 0 |
| builtin USER.md | 659 | 149 | 148 |
| notes files | — | 4 | 0 |
| notes chars | — | 5,396 | 0 |
| wiki files | — | 0 | 4 |
| wiki chars | — | 0 | 3,792 |
| index.md chars | — | 0 | 1,206 |
| index.md lines | — | 0 | 14 |
| transcript chars | — | 22,364 | 21,988 |

The memory folders themselves are in `memory/<arm>/` next to this file.

## What the dream pass said it changed

- verify: Corrected Tidewater standup from 10:15 to 9:40 per session local-872b9fded8bd40bab220d7e3566d608a58be6caa2be698791b6852b0c6771276.
- verify: Corrected Tidewater production region from eu-west-4 to eu-north-2 per session local-b3c9d963c216ed76e62d88fb6c6201dd2351a3701598027a5fd16ee75781f811.
- verify: Corrected Tidewater invoice retention from 180 days to 400 days per session local-21b282a00269fa5d28e35cdda0ab33d6da3a538e92567297ee7deba197796a59.
- verify: Corrected Tidewater certificate-expiry alarm action item from 14 days to 21 days per session local-200f9ed21664000edd9e1ea7565ff5e086e6e52192f3267bad573aee8d57df06.
- integrate: Consolidated project logs and working preferences into four linked wiki pages; retained current ownership, launch dates, budgets, deployment procedures and incident follow-ups, and removed fully covered notes.

## Every question

| id | question | base | raw | dream |
|---|---|---|---|---|
| r1 | Which bucket does ledgerd archive old invoice rows to? | ✓ lf-ledger-cold-07 | ✓ lf-ledger-cold-07 | ✓ lf-ledger-cold-07 |
| r2 | Who is beacon's SMS vendor and what do we pay per message? | ✓ Beacon’s SMS vendor is Pellucid SMS at €0.031 per message. | ✓ Pellucid SMS, €0.031 per message. | ✓ Pellucid SMS, €0.031 per message. |
| r3 | How many minutes did the beacon outage on October 20 last, and what was the root cause? | ✓ 47 minutes; an expired TLS certificate on beacon’s SMS gateway. | ✓ 47 minutes; an expired TLS certificate on beacon’s SMS gateway. | ✓ 47 minutes; caused by an expired TLS certificate on beacon’s SMS gateway. |
| r4 | What did the last harbor-api load test reach, and what is the target (requests per second)? | ✓ Last run: 1,120 requests per second; target: 1,350 requests per second. | ✓ Last run: 1,120 requests per second; target: 1,350 requests per second. | ✓ Last run: 1,120 requests per second; target: 1,350 requests per second. |
| r5 | Who is my contact at Brightwell Freight, and which cities are the pilot warehouses in? | ✓ Your contact is Ingrid Solheim; the pilot warehouses are in Malmö, Gdańsk, and Tallinn. | ✓ Ingrid Solheim; pilot warehouses in Malmö, Gdańsk, and Tallinn. | ✓ Ingrid Solheim; pilot warehouses in Malmö, Gdańsk and Tallinn. |
| r6 | A skiff deploy to ring 2 just failed with 'lease held'. What is the exact command that fixes it? | ✓ skiff lease release --ring 2 | ✓ skiff lease release --ring 2 | ✓ skiff lease release --ring 2 |
| m1 | What is the phone extension of the person who currently owns the service that stores invoices? | ✓ 4771 | ✓ 4771 | ✓ 4771 |
| m2 | Tomasz is out the week of November 16. Who covers his service, and what is that person's phone extension? | ✓ Kofi Mensah-Brandt covers harbor-api; extension 4099. | ✓ Kofi Mensah-Brandt covers harbor-api; phone extension 4099. | ✓ Kofi Mensah-Brandt covers harbor-api; extension 4099. |
| m3 | The beacon postmortem had one action item. What is its owner's phone extension, and which services does that person own now? | ✓ Sunniva Aaltonen, extension 4608; currently owns beacon and quaywatch. | ✓ Sunniva Aaltonen, extension 4608; currently owns beacon and quaywatch. | ✓ Sunniva Aaltonen, extension 4608; currently owns beacon and quaywatch. |
| m4 | At what euro amount does the Tidewater cloud cost alert fire, given the current budget? | ✓ €180,200 | ✓ €180,200 | ✓ €180,200 |
| m5 | How many days are there from the Brightwell pilot go-live date to the current Tidewater GA launch date? | ✓ 30 days | ✓ 30 days | ✓ 30 days. |
| s1 | What host and port should I use for the Tidewater staging database? | ✓ stg-db-22.lumenfold.internal:6543 | ✓ stg-db-22.lumenfold.internal:6543 | ✓ stg-db-22.lumenfold.internal:6543 |
| s2 | What is the current GA launch date for Tidewater? | ✓ 2026-12-09 | ✓ 2026-12-09 | ✓ 2026-12-09 |
| s3 | What is the exact command to deploy Tidewater to staging under the current policy? | ✓ skiff ship --env staging --ring 2 --ticket <ID> | ✓ skiff ship --env staging --ring 2 --ticket <ID> | ✓ skiff ship --env staging --ring 2 --ticket <ID> |
| s4 | Who owns ledgerd now? | ✓ Dario Nkemelu owns ledgerd, replacing Priya Raman effective 2026-10-26. | ✓ Dario Nkemelu | ✓ Dario Nkemelu |
| s5 | What is Tidewater's Q4 cloud budget? | ✓ €212,000 | ✓ €212,000 | ✓ €212,000 |
| c1 | What time is the Tidewater daily standup? | ✗ 10:15 in the Pier room. | ✓ 09:40 in the Pier room. | ✓ 09:40 in the Pier room. |
| c2 | How many days of retention does ledgerd keep for invoices? | ✓ 400 days | ✓ 400 days | ✓ 400 days |
| c3 | How many days before expiry does the Tidewater certificate alarm fire? | ✓ 21 days before expiry. | ✓ 21 days before expiry. | ✓ 21 days before expiry. |
| c4 | Which cloud region does Tidewater production run in? | ✗ eu-west-4 | ✓ eu-north-2 | ✓ eu-north-2 |
