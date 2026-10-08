"""Mortgage-rate outlook (docs/RATES_PLAN.md, registered before results).

The 30-year fixed mortgage rate h months ahead. Three candidate centers: no change, and the market's
implied 10-year Treasury yield (from the yield curve) plus a mortgage spread. The center is chosen and the
band is drawn walk-forward from each rule's own realized errors. Every forecast uses data through its
origin month only.

Usage: python -m rates.outlook [--snapshot data/snapshot/rates] [--out outputs/rates_outlook.json]
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd

MATURITIES = {"DGS1": 1, "DGS2": 2, "DGS3": 3, "DGS5": 5, "DGS7": 7, "DGS10": 10, "DGS20": 20, "DGS30": 30}
MORTGAGE = "MORTGAGE30US"
RULES = ("NO_CHANGE", "CURVE_FORWARD", "CURVE_FORWARD_LONG_SPREAD")
HORIZONS = tuple(range(6, 61, 6))
TEST_START = "1985-01"
HISTORY_START = "1972-01"
MIN_ERRORS = 60
BAND_TESTED = (0.70, 0.90)
MIN_TEST_ORIGINS = 120


def _r(x, places=3):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), places)


def load_monthly(source) -> pd.DataFrame:
    """Monthly averages of every series. `source` is a directory of FRED CSVs or a callable(series_id)."""
    frames = {}
    for sid in (*MATURITIES, MORTGAGE):
        if callable(source):
            df = source(sid)
        else:
            path = Path(source) / f"{sid}.csv"
            if not path.exists():
                continue
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        s = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()
        frames[sid] = s.resample("ME").mean()
    out = pd.DataFrame(frames)
    out.index = out.index.to_period("M")
    return out


def latest_weekly(source) -> tuple[str, float] | None:
    df = source(MORTGAGE) if callable(source) else pd.read_csv(Path(source) / f"{MORTGAGE}.csv", index_col=0, parse_dates=True)
    s = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()
    return (s.index[-1].date().isoformat(), float(s.iloc[-1])) if len(s) else None


def yield_at(row: pd.Series, years: float) -> float | None:
    """Linear interpolation across the maturities published that month (percent)."""
    pts = sorted((m, float(row[sid])) for sid, m in MATURITIES.items() if sid in row and row[sid] == row[sid])
    if len(pts) < 2:
        return None
    if years <= pts[0][0]:
        return pts[0][1]
    if years > pts[-1][0]:
        return None
    for (m0, y0), (m1, y1) in zip(pts, pts[1:]):
        if m0 <= years <= m1:
            return y0 + (y1 - y0) * (years - m0) / (m1 - m0)
    return None


def forward_10y(row: pd.Series, months: int) -> float | None:
    """Market-implied 10-year yield `months` ahead (percent), par yields treated as zero rates."""
    h = months / 12
    a, b = yield_at(row, h), yield_at(row, h + 10)
    if a is None or b is None:
        return None
    return 100 * (((1 + b / 100) ** (h + 10) / (1 + a / 100) ** h) ** (1 / 10) - 1)


def centers(data: pd.DataFrame, t, months: int) -> dict[str, float]:
    """Each rule's forecast made at month t, from data through t."""
    if t not in data.index or data.at[t, MORTGAGE] != data.at[t, MORTGAGE]:
        return {}
    hist = data.loc[:t]
    spread = (hist[MORTGAGE] - hist["DGS10"]).dropna()
    out = {"NO_CHANGE": float(data.at[t, MORTGAGE])}
    f = forward_10y(data.loc[t], months)
    if f is not None and len(spread) >= 3:
        out["CURVE_FORWARD"] = f + float(spread.iloc[-3:].mean())
        out["CURVE_FORWARD_LONG_SPREAD"] = f + float(spread.median())
    return out


def backtest(data: pd.DataFrame, horizons=HORIZONS) -> dict:
    """Walk-forward: forecasts at every origin, the rule chosen from realized errors, the band, coverage."""
    months = [p for p in data.index if str(p) >= HISTORY_START and data.at[p, MORTGAGE] == data.at[p, MORTGAGE]]
    last = months[-1]
    out = {}
    for h in horizons:
        forecasts = {}
        for t in months:
            c = centers(data, t, h)
            target = t + h
            if c:
                actual = data.at[target, MORTGAGE] if target in data.index else float("nan")
                forecasts[t] = (c, actual)
        errors_by_origin = {t: {r: a - v for r, v in c.items()} for t, (c, a) in forecasts.items() if a == a}
        rows = []
        for t in sorted(forecasts):
            if str(t) < TEST_START:
                continue
            c, actual = forecasts[t]
            known = [errors_by_origin[s] for s in errors_by_origin if s + h <= t]
            pick = choose_rule(known)
            band = band_from([e[pick] for e in known if pick in e]) if pick in c else None
            rows.append({"origin": str(t), "actual": actual, "centers": c, "rule": pick if pick in c else "NO_CHANGE", "band": band})
        out[h] = summarize(rows, h, str(last))
    return out


def choose_rule(known_errors: list[dict]) -> str:
    scored = {}
    for r in RULES:
        e = [abs(x[r]) for x in known_errors if r in x]
        if len(e) >= MIN_ERRORS:
            scored[r] = median(e)
    return min(scored, key=scored.get) if scored else "NO_CHANGE"


def band_from(errors: list[float]) -> dict | None:
    if len(errors) < MIN_ERRORS:
        return None
    q = np.percentile(errors, [10, 25, 50, 75, 90])
    return dict(zip(("e10", "e25", "e50", "e75", "e90"), map(float, q)))


def summarize(rows: list[dict], h: int, last: str) -> dict:
    done = [r for r in rows if r["actual"] == r["actual"]]
    rules = {}
    for rule in RULES:
        e = [r["actual"] - r["centers"][rule] for r in done if rule in r["centers"]]
        if e:
            rules[rule] = {"n": len(e), "mae": _r(np.mean(np.abs(e))), "median_abs_error": _r(median(map(abs, e))),
                           "mean_error": _r(np.mean(e))}
    chosen = [r for r in done if r["band"]]
    inside = [r["centers"][r["rule"]] + r["band"]["e10"] <= r["actual"] <= r["centers"][r["rule"]] + r["band"]["e90"] for r in chosen]
    pub_err = [abs(r["actual"] - r["centers"][r["rule"]]) for r in done]
    coverage = _r(np.mean(inside)) if inside else None
    status = ("TOO_FEW_TESTS" if len(chosen) < MIN_TEST_ORIGINS else "TOO_NARROW" if coverage < BAND_TESTED[0]
              else "TOO_WIDE" if coverage > BAND_TESTED[1] else "TESTED")
    decades = {}
    for d0 in (1985, 1990, 2000, 2010, 2020):
        d1 = d0 + (5 if d0 == 1985 else 10)
        sub = [r for r in done if d0 <= int(r["origin"][:4]) < d1]
        if sub:
            decades[f"{d0}-{d1 - 1}"] = {rule: _r(np.mean([abs(r["actual"] - r["centers"][rule]) for r in sub if rule in r["centers"]]))
                                        for rule in RULES if any(rule in r["centers"] for r in sub)}
    rule_counts = {}
    for r in done:
        rule_counts[r["rule"]] = rule_counts.get(r["rule"], 0) + 1
    return {"horizon_months": h, "origins_tested": len(done), "effective_independent_tests": round(len(done) / h, 1),
            "first_origin": done[0]["origin"] if done else None, "last_origin": done[-1]["origin"] if done else None,
            "rules": rules, "published_mae": _r(np.mean(pub_err)) if pub_err else None,
            "rule_chosen_share": {k: round(v / len(done), 3) for k, v in rule_counts.items()} if done else {},
            "band_coverage_10_90": coverage, "band_tests": len(chosen), "status": status, "mae_by_period": decades}


def outlook(data: pd.DataFrame, test: dict, weekly=None, horizons=HORIZONS) -> dict:
    """Today's outlook: for each horizon, the walk-forward-chosen center and the band from all realized errors."""
    t = max(p for p in data.index if data.at[p, MORTGAGE] == data.at[p, MORTGAGE] and data.at[p, "DGS10"] == data.at[p, "DGS10"])
    rows = []
    for h in horizons:
        c = centers(data, t, h)
        known = []
        months = [p for p in data.index if str(p) >= HISTORY_START and p + h <= t]
        for s in months:
            cs = centers(data, s, h)
            a = data.at[s + h, MORTGAGE] if (s + h) in data.index else float("nan")
            if cs and a == a:
                known.append({r: a - v for r, v in cs.items()})
        pick = choose_rule(known)
        pick = pick if pick in c else "NO_CHANGE"
        b = band_from([e[pick] for e in known if pick in e])
        center = c[pick]
        row = {"months": h, "month": str(t + h), "rule": pick, "center": _r(center, 2),
               "no_change": _r(c.get("NO_CHANGE"), 2), "curve_forward": _r(c.get("CURVE_FORWARD"), 2),
               "curve_forward_long_spread": _r(c.get("CURVE_FORWARD_LONG_SPREAD"), 2),
               "status": (test.get(h) or {}).get("status", "UNTESTED"),
               "band_coverage_10_90": (test.get(h) or {}).get("band_coverage_10_90")}
        if b:
            row.update({k: _r(max(0.0, center + b[e]), 2) for k, e in (("p10", "e10"), ("p25", "e25"), ("p50", "e50"), ("p75", "e75"), ("p90", "e90"))})
        rows.append(row)
    spread = (data[MORTGAGE] - data["DGS10"]).dropna()
    return {"as_of_month": str(t), "mortgage_30yr_month_avg": _r(data.at[t, MORTGAGE], 2),
            "mortgage_30yr_latest_weekly": None if not weekly else {"date": weekly[0], "rate": _r(weekly[1], 2)},
            "treasury_10y": _r(data.at[t, "DGS10"], 2), "spread_3m": _r(spread.loc[:t].iloc[-3:].mean(), 2),
            "spread_long_run_median": _r(spread.loc[:t].median(), 2),
            "forward_10y_in_36m": _r(forward_10y(data.loc[t], 36), 2), "horizons": rows}


def sep_context(source) -> dict | None:
    """FOMC SEP medians (committee members' projections, not market odds); context only."""
    try:
        md = source("FEDTARMD") if callable(source) else pd.read_csv(Path(source) / "FEDTARMD.csv", index_col=0, parse_dates=True)
        lr = source("FEDTARMDLR") if callable(source) else pd.read_csv(Path(source) / "FEDTARMDLR.csv", index_col=0, parse_dates=True)
    except Exception:
        return None
    md = pd.to_numeric(md.iloc[:, 0], errors="coerce").dropna()
    lr = pd.to_numeric(lr.iloc[:, 0], errors="coerce").dropna()
    return {"fed_funds_median_by_year": {str(d.year): _r(v, 3) for d, v in md.items()},
            "fed_funds_longer_run_median": _r(lr.iloc[-1], 3) if len(lr) else None,
            "longer_run_as_of": lr.index[-1].date().isoformat() if len(lr) else None,
            "note": "FOMC participants' own projections of the appropriate fed funds rate; not market odds and not mortgage rates."}


def build(source) -> dict:
    data = load_monthly(source)
    test = backtest(data)
    return {"method": "docs/RATES_PLAN.md", "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "outlook": outlook(data, test, latest_weekly(source)), "test": {str(h): v for h, v in test.items()},
            "fomc_sep_context": sep_context(source)}


def _fred(sid: str) -> pd.DataFrame:
    from pandas_datareader import data as web
    return web.DataReader(sid, "fred", "1962-01-01")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=None, help="directory of FRED CSVs (default: download)")
    parser.add_argument("--out", type=Path, default=Path("outputs/rates_outlook.json"))
    parser.add_argument("--notice", action="store_true", help="also print GitHub Actions notices")
    args = parser.parse_args(argv)
    result = build(args.snapshot if args.snapshot else _fred)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    o = result["outlook"]
    print(json.dumps({"as_of": o["as_of_month"], "now": o["mortgage_30yr_month_avg"],
                      "36m": next(r for r in o["horizons"] if r["months"] == 36),
                      "test_36m": result["test"]["36"]}, indent=1))
    if args.notice:
        for h in ("12", "36", "60"):
            r = next(x for x in o["horizons"] if str(x["months"]) == h)
            t = result["test"][h]
            print(f"::notice title=Rates {h} months::{r['rule']} {r.get('p10')} / {r.get('p50')} / {r.get('p90')} % (now {o['mortgage_30yr_month_avg']}%) | "
                  f"test {t['status']}, band coverage {t['band_coverage_10_90']}, MAE " + ", ".join(f"{k} {v['mae']}" for k, v in t["rules"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
