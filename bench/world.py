"""Benchmark scenario: 24 short "project log" sessions about a fictional team, then 20 questions.

Everything is invented, so no answer can be guessed or known from training. The log is built
to exercise what the Anthropic article says memory components are for:

- facts spread over many sessions, far more than fits an always-loaded memory file   (recall)
- answers that need facts from two or three different sessions                        (multi-hop)
- facts that later sessions change, sometimes twice                                   (superseded)
- a second, similar project (Estuary) whose numbers are easy to confuse with the first
- a planted note that mixes up the two projects, as a hurried note-taker would        (corrupted)
"""

SESSIONS = [
    ("2026-10-12", "Tidewater team ownership: harbor-api is owned by Tomasz Bielak, ledgerd by Priya Raman, "
                   "beacon by Sunniva Aaltonen, quaywatch by Dario Nkemelu. Daily standup is at 9:40 in the Pier "
                   "room. Kofi Mensah-Brandt is the engineering manager for all four services."),
    ("2026-10-13", "Tidewater infrastructure: the staging database is on host stg-db-14.lumenfold.internal, port 6432. "
                   "The production database is prd-db-03.lumenfold.internal, port 6432. Production runs in region "
                   "eu-north-2. We deploy with our in-house tool skiff; the staging deploy command is "
                   "`skiff ship --env staging --ring 2`."),
    ("2026-10-14", "ledgerd is the Tidewater service that stores invoices. They live in table inv_ledger_v3 with a "
                   "retention of 400 days; older rows are archived to the bucket lf-ledger-cold-07. The nightly "
                   "reconciliation job runs at 02:30 UTC."),
    ("2026-10-15", "The Tidewater GA launch date is November 18. The launch blocker is ticket TW-2291 (route cache "
                   "stampede). Our pilot customer is Brightwell Freight."),
    ("2026-10-16", "On-call phone extensions: Priya 4417, Tomasz 4532, Sunniva 4608, Dario 4771, Kofi 4099. If the "
                   "primary on-call does not acknowledge within 20 minutes, escalate to Kofi."),
    ("2026-10-19", "Tidewater's Q4 cloud budget is €184,000. The cost alert fires at 85% of budget. The cost "
                   "dashboard is called Ballast."),
    ("2026-10-19", "A separate project I get asked about, Estuary (analytics, not mine): its staging database is "
                   "est-stg-db-02.lumenfold.internal, port 5433. Its owner is Halvard Lindqvist (extension 4850). "
                   "Estuary's launch is planned for January 20 and its Q4 cloud budget is €96,000."),
    ("2026-10-20", "The Tidewater staging database moved today. New host: stg-db-22.lumenfold.internal, port 6543. "
                   "stg-db-14 will be decommissioned on October 23, so don't use it any more."),
    ("2026-10-21", "Yesterday (October 20) beacon had an outage that lasted 47 minutes. Root cause: an expired TLS "
                   "certificate on beacon's SMS gateway. The postmortem doc is PM-0312. Action item: raise an alarm "
                   "when any certificate is within 21 days of expiry; the owner of that action item is Sunniva."),
    ("2026-10-22", "Ownership change, effective October 26: ledgerd moves from Priya to Dario Nkemelu, because Priya "
                   "is moving to the Estuary project. At the same time quaywatch moves from Dario to Sunniva."),
    ("2026-10-23", "beacon's SMS vendor is Pellucid SMS: €0.031 per message, contract renews on January 9, 2027. "
                   "The fallback vendor is Northwire at €0.044 per message."),
    ("2026-10-23", "More Estuary notes: their outage last month lasted 112 minutes (disk full on est-stg-db-02). "
                   "They use Northwire directly for SMS. The Estuary standup is at 10:15 in the Lock room."),
    ("2026-10-26", "Tidewater GA has slipped from November 18 to December 2, because TW-2291 is not fixed yet. "
                   "There is a new blocker too: TW-2417 (invoice rounding in ledgerd)."),
    ("2026-10-27", "harbor-api load test: the target is 1,350 requests per second and the last run reached 1,120. "
                   "The bottleneck is the database connection pool of 64; the plan is to raise it to 96."),
    ("2026-10-28", "Brightwell Freight: my contact there is Ingrid Solheim. The pilot covers three warehouses, in "
                   "Malmö, Gdańsk and Tallinn. The pilot go-live is November 9."),
    ("2026-10-29", "Deploy policy change: every staging deploy now needs a change ticket, so the command is "
                   "`skiff ship --env staging --ring 2 --ticket <ID>`. Also, there is now a deploy freeze every "
                   "Thursday from 14:00 to 18:00."),
    ("2026-10-30", "Estuary again: retention on their event tables is 180 days, their production region is "
                   "eu-west-4, and their certificate alarms fire at 14 days before expiry."),
    ("2026-11-02", "Steering committee decision: Tidewater GA is now December 9, and that is final. TW-2291 is "
                   "fixed in build 5.8.3. TW-2417 is still open and Dario owns it."),
    ("2026-11-03", "My working preferences: short bullet points, metric units, 24-hour times, and dates written "
                   "like 2026-11-09. My working hours are 08:00 to 16:30 Stockholm time."),
    ("2026-11-04", "Tidewater's Q4 cloud budget was raised from €184,000 to €212,000; the alert threshold stays at "
                   "85%. Tomasz is on leave November 16 to 27, and Kofi covers harbor-api while he is out."),
    ("2026-11-05", "The Tidewater security review is scheduled for November 24 with reviewer Anneli Korhonen. Scope: "
                   "harbor-api auth and the ledgerd export endpoints. The pen-test report ID is SR-0447."),
    ("2026-11-05", "Estuary's Q4 budget was cut from €96,000 to €81,000 and their launch moved to February 3."),
    ("2026-11-06", "A gotcha we hit today: skiff deploys to ring 2 fail with 'lease held' when quaywatch is in the "
                   "middle of a scan. The fix is to run `skiff lease release --ring 2` and retry. Scans start at "
                   "15 minutes past each hour and take about 6 minutes."),
    ("2026-11-09", "The Brightwell pilot went live today as planned. First-day volume was 18,400 routed parcels. "
                   "Ingrid wants a weekly report every Monday at 09:00."),
]

# A note as a hurried agent might have written it: four Tidewater "facts" that are really
# Estuary's values (sessions 12 and 17). Planted into the plugin's notes folder before the
# dream pass. The transcripts contradict every line.
PLANTED_NOTE_PATH = "notes/tidewater-quick-reference.md"
PLANTED_NOTE = """\
# Tidewater quick reference
- Daily standup: 10:15 in the Pier room
- ledgerd invoice retention: 180 days
- Certificate expiry alarm: fires 14 days before expiry
- Production region: eu-west-4
"""

# all: every pattern must match the ANSWER line. none: no pattern may match it.
QUESTIONS = [
    # --- recall: one fact, one session
    {"id": "r1", "group": "recall", "q": "Which bucket does ledgerd archive old invoice rows to?",
     "all": [r"lf-ledger-cold-07"]},
    {"id": "r2", "group": "recall", "q": "Who is beacon's SMS vendor and what do we pay per message?",
     "all": [r"pellucid", r"0[.,]031"]},
    {"id": "r3", "group": "recall", "q": "How many minutes did the beacon outage on October 20 last, and what was the root cause?",
     "all": [r"\b47\b", r"cert"], "none": [r"\b112\b"]},
    {"id": "r4", "group": "recall", "q": "What did the last harbor-api load test reach, and what is the target (requests per second)?",
     "all": [r"1[,. ]?120", r"1[,. ]?350"]},
    {"id": "r5", "group": "recall", "q": "Who is my contact at Brightwell Freight, and which cities are the pilot warehouses in?",
     "all": [r"ingrid", r"malm", r"gda", r"tallinn"]},
    {"id": "r6", "group": "recall", "q": "A skiff deploy to ring 2 just failed with 'lease held'. What is the exact command that fixes it?",
     "all": [r"skiff lease release --ring 2"]},
    # --- multi-hop: needs facts from two or three sessions
    {"id": "m1", "group": "multi-hop", "q": "What is the phone extension of the person who currently owns the service that stores invoices?",
     "all": [r"\b4771\b"], "none": [r"\b4417\b"]},
    {"id": "m2", "group": "multi-hop", "q": "Tomasz is out the week of November 16. Who covers his service, and what is that person's phone extension?",
     "all": [r"kofi", r"\b4099\b"]},
    {"id": "m3", "group": "multi-hop", "q": "The beacon postmortem had one action item. What is its owner's phone extension, and which services does that person own now?",
     "all": [r"\b4608\b", r"beacon", r"quaywatch"]},
    {"id": "m4", "group": "multi-hop", "q": "At what euro amount does the Tidewater cloud cost alert fire, given the current budget?",
     "all": [r"180[,. ]?200"], "none": [r"156[,. ]?400"]},
    {"id": "m5", "group": "multi-hop", "q": "How many days are there from the Brightwell pilot go-live date to the current Tidewater GA launch date?",
     "all": [r"\b30\b"]},
    # --- superseded: a later session changed the answer
    {"id": "s1", "group": "superseded", "q": "What host and port should I use for the Tidewater staging database?",
     "all": [r"stg-db-22", r"\b6543\b"], "none": [r"stg-db-14", r"est-stg", r"\b6432\b", r"\b5433\b"]},
    {"id": "s2", "group": "superseded", "q": "What is the current GA launch date for Tidewater?",
     "all": [r"(dec(ember)?\.? 0?9\b|\b0?9(th)? (of )?dec|12-09)"], "none": [r"nov(ember)?\.? 18", r"dec(ember)?\.? 0?2\b", r"11-18", r"12-02"]},
    {"id": "s3", "group": "superseded", "q": "What is the exact command to deploy Tidewater to staging under the current policy?",
     "all": [r"skiff ship --env staging --ring 2 --ticket"]},
    {"id": "s4", "group": "superseded", "q": "Who owns ledgerd now?",
     "all": [r"dario"], "none": [r"^\W*priya", r"priya( raman)? (owns|is the owner|still)"]},
    {"id": "s5", "group": "superseded", "q": "What is Tidewater's Q4 cloud budget?",
     "all": [r"212[,. ]?000"], "none": [r"184[,. ]?000", r"96[,. ]?000", r"81[,. ]?000"]},
    # --- corrupted: the planted note says otherwise (plugin arms only; baseline has no planted note)
    {"id": "c1", "group": "corrupted-note", "q": "What time is the Tidewater daily standup?",
     "all": [r"\b0?9[:.]40\b"], "none": [r"10[:.]15"]},
    {"id": "c2", "group": "corrupted-note", "q": "How many days of retention does ledgerd keep for invoices?",
     "all": [r"\b400\b"], "none": [r"\b180\b"]},
    {"id": "c3", "group": "corrupted-note", "q": "How many days before expiry does the Tidewater certificate alarm fire?",
     "all": [r"\b21\b"], "none": [r"\b14\b"]},
    {"id": "c4", "group": "corrupted-note", "q": "Which cloud region does Tidewater production run in?",
     "all": [r"eu-north-2"], "none": [r"eu-west-4"]},
]

# In-place corruption: the same four facts, but damaged inside whatever notes each arm wrote
# itself (built-in MEMORY.md for the baseline, notes/ for the plugin). The transcripts stay
# intact, so this asks: when a system's own note is wrong, does it recover the truth?
CORRUPTIONS = [
    ("standup time 9:40 → 10:15", r"\b0?9[:.]40\b", "10:15"),
    ("retention 400 → 180 days", r"\b400(?=[ -]?days?)", "180"),
    ("cert alarm 21 → 14 days", r"\b21(?=[ -]?days?)", "14"),
    ("prod region eu-north-2 → eu-west-4", r"eu-north-2", "eu-west-4"),
]

INGEST_PROMPT = ("Project log, {date}. Please keep track of this for later; a one-line acknowledgement is enough.\n\n"
                 "{text}")

QUESTION_PROMPT = ("{q}\n\nAnswer from what you know about my projects from our earlier sessions. End with one "
                   "line that starts with `ANSWER:` and contains only the answer.")
