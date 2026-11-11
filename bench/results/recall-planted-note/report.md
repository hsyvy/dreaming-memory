# Dreaming memory plugin — benchmark results

Run `20261111-175638` · model `gpt-6.1-sol` · Hermes Agent v0.23.1+1921.g4ed1425 (2026.9.24) · stable · local 4ed14253ea7b

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
| corrupted-note ¹ | 4/4 | 4/4 | 4/4 |
| **All questions** | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) |

¹ One wrong note is planted, only in the two plugin arms (it lives in the plugin's notes folder). For `base` this group is plain recall with nothing misleading it.

## Cost of answering a question (mean per question)

| | base | raw | dream |
|---|---|---|---|
| Model calls | 1.6 | 1.4 | 1.1 |
| Input tokens | 7,140 | 6,563 | 4,787 |
| Output tokens | 42 | 27 | 18 |
| Auxiliary model calls | 0.0 | 0.0 | 0.0 |
| Seconds | 6.7 | 5.4 | 4.5 |

## Cost of remembering

| | base | raw | dream |
|---|---|---|---|
| Model calls over all sessions | 49 | 48 | 48 |
| Input tokens over all sessions | 174,799 | 201,527 | 202,462 |
| Seconds over all sessions | 250 | 216 | 207 |
| Dream pass | — | — | 3 calls, 48.8s |

## What each arm had in memory when the questions started

| | base | raw | dream |
|---|---|---|---|
| builtin MEMORY.md | 2,123 | 0 | 0 |
| builtin USER.md | 140 | 135 | 149 |
| notes files | — | 5 | 0 |
| notes chars | — | 5,628 | 0 |
| wiki files | — | 0 | 4 |
| wiki chars | — | 0 | 3,853 |
| index.md chars | — | 0 | 1,207 |
| index.md lines | — | 0 | 14 |
| transcript chars | — | 22,236 | 22,502 |

The memory folders themselves are in `memory/<arm>/` next to this file.

## What the dream pass said it changed

- verify: Corrected Tidewater standup from 10:15 to 9:40 per session local-a92dd6ce85807340428e6390e54cf1d2f62a30f8442e2d6f5c4d5ef6006619e4 (2026-10-12 project log).
- verify: Corrected ledgerd invoice retention from 180 days to 400 days per session local-a29e77c5a6ca77cc2718b78ff2e3207170251159d1bd1918499bc855a7066382 (2026-10-14 project log).
- verify: Corrected Tidewater certificate expiry alarm from 14 days to 21 days per session local-517b15e01a8e8a60f84ee6b7e8dee66ee23210fdc030b33b2f6557de70edcae9 (2026-10-21 project log).
- verify: Corrected Tidewater production region from eu-west-4 to eu-north-2 per session local-8eac4a8280f37e81581a4694210d4169f68503fffd7ff415901d3cb88ca5f997 (2026-10-13 infrastructure log).
- integrate: Consolidated project logs and preferences into current-state wiki pages using the supplied transcripts; retained current ownership, launch dates, budgets and deployment rules, clarified the certificate alarm as an action item, and removed fully covered notes.

## Every question

| id | question | base | raw | dream |
|---|---|---|---|---|
| r1 | Which bucket does ledgerd archive old invoice rows to? | ✓ lf-ledger-cold-07 | ✓ lf-ledger-cold-07 | ✓ lf-ledger-cold-07 |
| r2 | Who is beacon's SMS vendor and what do we pay per message? | ✓ Pellucid SMS, €0.031 per message. | ✓ Pellucid SMS, €0.031 per message. | ✓ Pellucid SMS, €0.031 per message; fallback: Northwire, €0.044 per message. |
| r3 | How many minutes did the beacon outage on October 20 last, and what was the root cause? | ✓ 47 minutes; an expired TLS certificate on beacon’s SMS gateway. | ✓ 47 minutes; an expired TLS certificate on beacon’s SMS gateway. | ✓ 47 minutes; an expired TLS certificate on beacon’s SMS gateway. |
| r4 | What did the last harbor-api load test reach, and what is the target (requests per second)? | ✓ Last run: 1,120 requests per second; target: 1,350 requests per second. | ✓ Last run: 1,120 requests per second; target: 1,350 requests per second. | ✓ Last run: 1,120 requests per second; target: 1,350 requests per second. |
| r5 | Who is my contact at Brightwell Freight, and which cities are the pilot warehouses in? | ✓ Your contact is Ingrid Solheim; the pilot warehouses are in Malmö, Gdańsk and Tallinn. | ✓ Ingrid Solheim; pilot warehouses in Malmö, Gdańsk, and Tallinn. | ✓ Ingrid Solheim; pilot warehouses in Malmö, Gdańsk, and Tallinn. |
| r6 | A skiff deploy to ring 2 just failed with 'lease held'. What is the exact command that fixes it? | ✓ skiff lease release --ring 2 | ✓ skiff lease release --ring 2 | ✓ skiff lease release --ring 2 |
| m1 | What is the phone extension of the person who currently owns the service that stores invoices? | ✓ 4771 | ✓ 4771 | ✓ 4771 |
| m2 | Tomasz is out the week of November 16. Who covers his service, and what is that person's phone extension? | ✓ Kofi Mensah-Brandt covers harbor-api; extension 4099. | ✓ Kofi Mensah-Brandt covers harbor-api; phone extension 4099. | ✓ Kofi Mensah-Brandt covers harbor-api; phone extension 4099. |
| m3 | The beacon postmortem had one action item. What is its owner's phone extension, and which services does that person own now? | ✓ Sunniva Aaltonen — extension 4608; currently owns beacon and quaywatch. | ✓ Sunniva Aaltonen, extension 4608; currently owns beacon and quaywatch. | ✓ Sunniva Aaltonen, extension 4608; currently owns beacon and quaywatch. |
| m4 | At what euro amount does the Tidewater cloud cost alert fire, given the current budget? | ✓ €180,200 | ✓ €180,200 | ✓ €180,200 |
| m5 | How many days are there from the Brightwell pilot go-live date to the current Tidewater GA launch date? | ✓ 30 days. | ✓ 30 days. | ✓ 30 days |
| s1 | What host and port should I use for the Tidewater staging database? | ✓ stg-db-22.lumenfold.internal:6543 | ✓ stg-db-22.lumenfold.internal:6543 | ✓ stg-db-22.lumenfold.internal:6543 |
| s2 | What is the current GA launch date for Tidewater? | ✓ 2026-12-09 | ✓ 2026-12-09 | ✓ 2026-12-09 |
| s3 | What is the exact command to deploy Tidewater to staging under the current policy? | ✓ skiff ship --env staging --ring 2 --ticket <ID> | ✓ skiff ship --env staging --ring 2 --ticket <ID> | ✓ skiff ship --env staging --ring 2 --ticket <ID> |
| s4 | Who owns ledgerd now? | ✓ Dario Nkemelu owns ledgerd, effective 2026-10-26. | ✓ Dario Nkemelu | ✓ Dario Nkemelu |
| s5 | What is Tidewater's Q4 cloud budget? | ✓ €212,000. | ✓ €212,000 | ✓ €212,000 |
| c1 | What time is the Tidewater daily standup? | ✓ 09:40 in the Pier room. | ✓ 09:40 in the Pier room. | ✓ 09:40 (timezone unspecified) |
| c2 | How many days of retention does ledgerd keep for invoices? | ✓ 400 days | ✓ 400 days | ✓ 400 days |
| c3 | How many days before expiry does the Tidewater certificate alarm fire? | ✓ 21 days before expiry | ✓ 21 days before expiry | ✓ 21 days before expiry. |
| c4 | Which cloud region does Tidewater production run in? | ✓ eu-north-2 | ✓ eu-north-2 | ✓ eu-north-2 |
