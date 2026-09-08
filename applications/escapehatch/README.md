# EscapeHatch

Ops data trapped in a desktop spreadsheet, no API, a web portal that expects a
file. People screenshot the sheet and retype it. EscapeHatch does the handoff
instead: **Solari Desktop** opens the real workbook in LibreOffice Calc and
exports CSV, **Solari Sandbox** normalizes that CSV to a strict schema, **Solari
Browser** files the artifact into a portal we host on a public preview URL and
comes back with a receipt.

One `slr_live_` key. Three surfaces. One `EscapeRun`.

This is not a Worldline remix. There is no tournament, no snapshot fork, no
competing plan. The problem is extraction and delivery: get the bytes out of a
GUI that will not speak HTTP, prove they mean what we think, and prove the
portal actually stored them.

## Why three surfaces

The workbook only exists as a GUI document. A headless `soffice --convert-to`
would cheat the constraint the operators live with — they click File → Save As.
Desktop drives that path on the `default` template, where LibreOffice is
already installed.

The portal cannot run on your laptop. The cloud browser cannot reach
`localhost`, and a real intake backend would not either. The sandbox hosts the
normalizer *and* the portal, then mints a `*.preview.getsolari.com` URL.

The browser is the operator. It uploads the normalized JSON the way a person
would and we assert the receipt through `/seen` and `/receipts/:id`, not by
trusting a thank-you page.

Concurrency stays at two live VMs: desktop alone, then destroy; sandbox +
browser together, then destroy. Every path hits `finally`.

## How to run

```bash
cd applications/escapehatch
python -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m unittest discover -s tests -v
python -m escapehatch --dry-run
```

`--dry-run` never calls Solari. It walks the same `EscapeRun` state machine on
the committed fixtures, files the artifact into a local copy of the portal, and
writes `evidence/run.json`.

For a live run, copy `.env.example` to `.env` and put a key in it (or export
`SOLARI_API_KEY`). One key covers desktop, sandbox, and browser.

```bash
python -m escapehatch
```

Desktop recording is on by default (`record: true`). Pass `--no-record` to skip
it. The playback URL, if any, is stored on the run after query parameters are
stripped.

## Evidence

A finished run writes `evidence/`:

```
evidence/run.json
evidence/extract.csv
evidence/normalized.json
evidence/screens/desktop-calc-open.png
evidence/screens/desktop-save-as.png
evidence/screens/desktop-exported.png
evidence/screens/browser-portal.png
evidence/screens/browser-receipt.png
```

`run.json` is an `EscapeRun`:

```
id, status, desktopSessionId?, extractPath?, extractSha256?,
normalizedJsonPath?, normalizedSha256?, portalUrl?, portalReceipt?,
browserSessionId?, recordingUrl?, evidenceDir, error?
```

Statuses move as a state machine, not a set of flags:

`created → desktop_running → extracted → normalizing → normalized → portal_up → filing → filed → cleaned | failed`

Session ids are shortened. API keys and presigned query strings are stripped.
The key is never copied into evidence.

## Three-minute demo

1. Install and run the tests (about thirty seconds). They pin the normalizer
   against `fixtures/ops-hold-log.csv` — five messy hold-log rows become a
   digest-stable JSON document.
2. `python -m escapehatch --dry-run`. Open `evidence/run.json`. You should see
   `status: cleaned`, a `rcpt_…` receipt, and both extract and normalized
   digests.
3. If you have a key, run without `--dry-run`. Watch the desktop stream URL
   while Calc exports, then the portal preview URL while the browser files.
   `run.json` should name all three surfaces and a receipt that `/receipts/:id`
   can confirm before the VMs disappear.

The fixture is a Pinetree cold-chain nightly hold log: mixed date formats,
shouty statuses, a missing operator. That is the spreadsheet someone would
otherwise retype.
