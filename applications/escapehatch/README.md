# EscapeHatch

Ops data is trapped in a shop-floor Calc workbook. There is no API. The CSV
export button on the old PC is the one nobody trusts. People screenshot rows
and retype them into a web portal. Lot IDs get transposed. Quantities flip
sign.

EscapeHatch is the escape hatch. One Solari key drives three surfaces. One
`EscapeRun` is the record.

1. **Desktop** opens the night-shift ticket workbook in LibreOffice Calc and
   exports a CSV through the real GUI.
2. **Sandbox** normalizes that CSV into a strict JSON schema, drops bad rows,
   and hosts a closeout portal on a public preview URL.
3. **Browser** files the normalized batch into that portal and keeps the
   receipt.

This is not a fork of Worldline. There are no candidate plans and no
checkpoints. The point is a single controlled handoff out of a GUI that cannot
speak HTTP.

## Why three surfaces

The workbook only exists as a desktop app. A headless convert would skip the
system operators actually use.

The normalizer has to run off the desktop. The guest that just clicked menus
is the last place you want to trust a schema.

The portal has to live on a public URL. A Solari browser cannot POST to your
laptop, and a real closeout desk would not either.

## Status machine

```
created → desktop_running → extracted → normalizing → normalized
        → portal_up → filing → filed → cleaned
                                         ↘ failed
```

An `EscapeRun` holds the session ids, paths, SHA-256 digests, portal URL,
receipt, recording URL, and error. Status is a typed progression. It is not a
pile of booleans.

## How to run

```bash
cd applications/escapehatch
python -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Dry-run explains every phase and runs the normalizer on the fixture CSV. It
does not call Solari.

```bash
python -m escapehatch --dry-run
```

Live mode needs a key. Copy `.env.example` to `.env` and set `SOLARI_API_KEY`.
The key is never written to evidence.

```bash
python -m escapehatch
```

Starter plans cap concurrent VMs at about two. The pipeline stays inside that:

1. Desktop only. Destroy it.
2. Sandbox normalizes and serves the portal.
3. Browser runs next to that sandbox. Then everything is destroyed.

`kill` / `destroy` always run in `finally` blocks.

If LibreOffice is missing on `default`, retry with
`--desktop-template office`.

## Tests

```bash
python -m unittest discover -s tests -v
```

The normalizer tests are pure functions. Fixture CSV in, expected JSON and
digest out. No API key.

## What evidence looks like

`evidence/run.json` is the canonical report. A live run also writes:

- `extract.csv` and its SHA-256
- `normalized.json` and its SHA-256
- `screens/desktop-calc-open.png`
- `screens/desktop-exported.png`
- `screens/browser-portal.png`
- `screens/browser-receipt.png`
- `portal-batch.json` (what the browser filed)
- `recordingUrl` when the desktop was created with `record=true`

API keys, `pt_token` query values, and `slr_live_…` strings are redacted.
Session ids are shortened.

A dry-run report has `mode: "dry-run"`, local normalize counts, and no session
ids.

## Demo script (about 3 minutes)

1. Install as above and run `python -m escapehatch --dry-run`.
2. Open `evidence/run.json`. Confirm the three planned surfaces and the
   local digest `0b92f6f0ed70e3a40b4ea63e6e0dd9d3667320d376740a533146b067136c76a6`.
3. Open `fixtures/night-shift-tickets.csv`. Three rows are dirty on purpose
   (negative qty, invented status, broken line). The normalizer keeps three
   and rejects three.
4. If you have a key, run `python -m escapehatch`. Watch the desktop stream
   URL if you want to see Calc export the CSV.
5. When it finishes, `evidence/run.json` should show `status: cleaned`, a
   `portal_receipt` like `RCPT-…`, and screenshots from both GUI surfaces.

## Fixture

`fixtures/night-shift-tickets.ods` is a real Calc workbook built from the CSV.
The live desktop path uploads that workbook and drives File → Save As → CSV.
The dirty rows stay in the extract so the sandbox step has something to refuse.
