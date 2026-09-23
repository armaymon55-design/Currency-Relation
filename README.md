# Currency Correlation Platform

Measures, for every G10 currency pair and every currency index, three things:
**which way** they move together (direct / inverse), **how much** (beta: % pair move per
1% index move) and **how reliable** that is (correlation, R²) — and whether today's reading
is normal for that pair. Standalone project; not wired into the macro platform.

## Data

Read-only feed from the XM MetaTrader 5 terminal via the official `MetaTrader5` package.
The client attaches by login number + server; the password stays in the terminal.
`tests/test_readonly.py` fails the build if any trading call is ever added to the client.

- 34 of 45 G10 pairs come straight from broker symbols (`…m#` series); the 11 missing
  SEK/NOK crosses are built exactly from their USD legs.
- Broker clock is New York + 7 h; everything is normalised to UTC (`src/data/broker_time.py`).
- Bars are cached per symbol/timeframe in `data_cache/` and only the new tail is fetched.

## Indices

- `DXY` — the published ICE formula from six legs (checked against XM's `USDX-DEC26` futures CFD).
- `<CCY>-EW` — equal-weight strength for each of the 10 currencies. Exact split:
  ln-return(A/B) = strength_return(A) − strength_return(B).
- When a pair is related to one of its own currencies, the index used leaves the
  counterpart out, so the basket doesn't already contain the pair.

## Run

```
C:\Users\ahmed\AppData\Local\Programs\Python\Python313\python.exe -m pytest tests -q
C:\Users\ahmed\AppData\Local\Programs\Python\Python313\python.exe scripts\run_matrix.py
```

Python 3.13 (the `MetaTrader5` package has no 3.14 build yet). Outputs land in `output/`:
`matrix.csv`, `attribution.csv`, `indices_<tf>.csv`, `pair_closes_<tf>.pkl`, `universe.json`, `report.txt`.

## Live (updater + dashboard)

Double-click `start_live.bat`, or run the two processes yourself:

```
C:\Users\ahmed\AppData\Local\Programs\Python\Python313\python.exe scripts\live.py
C:\Users\ahmed\AppData\Local\Programs\Python\Python313\python.exe app\server.py
```

`scripts/live.py` re-measures every `REFRESH_MINUTES` (5) while the market is open — about
20 s per cycle after the first — writes all outputs atomically (`output/.tmp` then move,
`matrix.csv` last) and a heartbeat (`output/heartbeat.json`), logs to `output/live.log`
(rotating), skips the recompute when no tick has arrived (weekend), and survives a failed
cycle. The dashboard polls `/api/status` every 30 s, shows "Live · updated N min ago" (amber
if the last good update is older than `STALE_MINUTES`, or if the updater reported an error)
and redraws itself when a new snapshot lands, keeping your selection.

Needs the XM MT5 terminal installed on the machine (the updater launches it if closed) and
the machine awake. For true 24/7 on a Windows VPS, register both scripts as services with
NSSM (`nssm install cc-live  <python> <path>\scripts\live.py` and the same for
`app\server.py`); NSSM restarts them if they ever exit.

## Dashboard (Tab 1)

```
C:\Users\ahmed\AppData\Local\Programs\Python\Python313\python.exe app\server.py
```

then open http://127.0.0.1:5050. It reads only `output/` and the bar cache (never the
terminal), picks up a fresh `run_matrix.py` run automatically, and shows:

- three tiles for the focused pair × index — which way, ratio, reliability — plus a
  health pill (normal / tighter than normal / looser than normal / seesaw broken / no real link)
- the split bar: how much of the pair's move was the base currency vs the quote
- the what-if box: pick an index and a move ("if DXY moves +1%"), get the implied move for
  all 45 pairs from today's ratios, ranked by impact, each with the range implied by that
  ratio's own normal band and how reliable the link is right now. Conditional arithmetic,
  not a forecast — pairs with no reliable link are greyed out and sink to the bottom
  (`/api/whatif`, `src/engine/whatif.py`).
- the seesaw-health chart: rolling correlation over the last 300 bars with its normal band
- the 45 × 11 relationship grid (click a cell to focus it) and the "not normal right now" list

Timeframe (H1 / H4 / D1) and window (20 / 50 / 100 bars) switch at the top.

## 3D currency map (Tab 2)

`/api/map` serves the currency-level view: 10 nodes (each currency's strength move over
the recent window) and 45 links (correlation between two currencies' strength indices
over the current window, each with its own normal band and health state). The page draws
it with `3d-force-graph` (WebGL; a 2D `force-graph` fallback kicks in without WebGL).
Currencies whose strengths move together are pulled close by the physics layout, so the
blocs separate on their own. Bloc colours are structural — from the leading eigenvector of
the long-lookback correlation matrix (`src/engine/blocs.py`) — and on G10 data that split
is the high-beta bloc (AUD NZD SEK NOK) against the core bloc (USD EUR GBP JPY CHF CAD).
Labels are an HTML overlay positioned from the graph's own projection (no extra three.js).

The server runs under `waitress` when installed (stable keep-alive, threaded); it falls
back to Flask's development server otherwise.

## Layout

```
config.py                 universe, feed, thresholds (no secrets)
src/data/broker_time.py   server time <-> UTC
src/data/universe.py      pair convention, symbol resolution, synthetic crosses
src/data/mt5_client.py    read-only MT5 client with CSV cache
src/indices/synthetic.py  DXY (ICE) + equal-weight strengths (+ leave-one-out)
src/engine/relations.py   rolling rho / beta / R2, sign, strength, normal bands
src/engine/health.py      HEALTHY / WARNING / BREAKDOWN / NO_LINK
src/engine/attribution.py base-vs-quote split of a pair's move
scripts/run_matrix.py     step 1 entry point
tests/                    pytest, no terminal needed
```
