# Public site (Vercel)

A static, public edition of the dashboard built from the **ECB's daily euro reference
rates** — a source whose terms allow public display. It shares the measurement engine with
the private platform and differs in three deliberate ways: daily bars only, no ICE-formula
dollar index (the equal-weight USD basket instead), and every number precomputed to JSON.

```
python -m public.build          # -> public/site/data/*  (about 4 MB, ~10 s + download)
```

Preview locally: run the private dashboard (`app/server.py`) and open
http://127.0.0.1:5050/public/ — it serves `public/site` exactly as Vercel will.

## One-time setup

1. **GitHub repository** for this folder (`currency_correlation/`). Public keeps GitHub
   Actions free and unlimited; private is fine too (2,000 free minutes a month, the daily
   build uses ~2). `.env`, `data_cache/`, `output/` and `public/site/data/` are ignored.
2. **Run the workflow once**: Actions → *publish public site* → *Run workflow*. It builds the
   site and force-pushes it to a branch named `site` (one commit, so the repo never bloats).
3. **Vercel**: *Add New Project* → import the repository → Framework preset **Other**,
   Root Directory `/`, no build command, Output Directory `.` → in *Settings → Git* set the
   **Production Branch to `site`** → Deploy. That's the URL for LinkedIn.

From then on the workflow runs every working day at 15:45 UTC (after the ~16:00 CET fix),
pushes the new build, and Vercel redeploys automatically. No tokens or secrets are needed:
the workflow uses the repository's own `GITHUB_TOKEN`.

## Things to know

- **GitHub disables scheduled workflows after 60 days without repository activity.** The
  daily bot commit lands on the `site` branch, which counts as activity, but check the
  Actions tab now and then; re-enabling is one click.
- Vercel's free (Hobby) plan is for non-commercial use. A personal portfolio page is fine;
  if this becomes marketing for a business, move it to Pro ($20/month).
- The public build never touches MetaTrader, XM or any broker data. Keep it that way:
  XM's client agreement (cl. 15.3, 86.6) forbids redistributing their prices.
- The name "U.S. Dollar Index" / "DXY" / "USDX" and its formula belong to ICE; the public
  site uses only the equal-weight USD basket and says so on the about page.
