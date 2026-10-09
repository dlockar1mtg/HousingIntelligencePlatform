from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scoring.entry_score import signal_strength

def n(v, default=0.0):
    try:
        if v is None or pd.isna(v): return default
        return float(v)
    except Exception:
        return default

def load_profile(input_dir):
    p = Path(input_dir) / "personal_profile.json"
    if not p.exists(): return {}
    return json.loads(p.read_text(encoding="utf-8"))

def payment(principal, rate, years):
    r = rate / 100 / 12
    m = years * 12
    if principal <= 0: return 0.0
    if r == 0: return principal / m
    return principal * (r * (1+r)**m) / ((1+r)**m - 1)

def personal_score(profile, price, rate):
    if not profile:
        return {"score": np.nan, "label": "Profile Missing", "dti": np.nan, "cash_gap": np.nan, "comfortable_price": np.nan}
    inc = profile.get("income", {})
    cash = profile.get("cash_assets", {})
    debt = profile.get("debts", {})
    credit = profile.get("credit", {})
    home = profile.get("home_purchase", {})
    budget = profile.get("monthly_budget", {})
    prefs = profile.get("preferences", {})
    asm = profile.get("assumptions", {})

    annual = n(inc.get("gross_annual_salary")) + n(inc.get("annual_bonus")) + n(inc.get("other_annual_income"))
    gross_m = n(budget.get("gross_monthly_income")) or annual/12
    monthly_debt = n(debt.get("monthly_debt_payments"))
    down_pct = n(home.get("desired_down_payment_percent"), 20)
    closing_pct = n(home.get("estimated_closing_cost_percent"), 3)
    reserved = n(cash.get("cash_reserved_for_down_payment"))
    emergency = n(cash.get("emergency_fund"))
    tax_pct = n(asm.get("property_tax_percent"), 1.3)
    ins_pct = n(asm.get("homeowners_insurance_percent"), 0.4)
    maint_pct = n(asm.get("expected_home_maintenance_percent"), 1.0)
    hoa = n(asm.get("hoa_monthly"))

    loan = price * (1-down_pct/100)
    total = payment(loan, rate, 30) + price*(tax_pct+ins_pct+maint_pct)/100/12 + hoa
    dti = (total + monthly_debt)/gross_m if gross_m else np.nan
    cash_need = price*(down_pct+closing_pct)/100
    cash_gap = max(0, cash_need-reserved)

    score = 0
    cs = n(credit.get("credit_score"))
    score += 25 if cs>=800 else 23 if cs>=760 else 20 if cs>=720 else 16 if cs>=680 else 12 if cs>=640 else 8 if cs>=600 else 4
    saved_pct = reserved/price*100 if price else 0
    score += 20 if saved_pct>=20 else 17 if saved_pct>=15 else 14 if saved_pct>=10 else 10 if saved_pct>=5 else 6 if saved_pct>=3 else 2

    exp = sum(n(budget.get(k)) for k in ["housing_rent","utilities","food","transportation","insurance","subscriptions","childcare","other_expenses"]) + monthly_debt
    months = emergency/exp if exp else 0
    score += 15 if months>=12 else 13 if months>=9 else 10 if months>=6 else 6 if months>=3 else 2

    dti_pct = dti*100 if pd.notna(dti) else 999
    score += 20 if dti_pct<20 else 18 if dti_pct<=30 else 15 if dti_pct<=36 else 10 if dti_pct<=43 else 5 if dti_pct<=50 else 0

    years = n(inc.get("employment_years"))
    score += 10 if years>=2 else 8 if years>=1 else 6 if years>0 else 3
    goals = profile.get("goals", {})
    checks = [price>0, bool(profile.get("profile",{}).get("primary_market")), bool(goals.get("target_move_in_date")), bool(goals.get("must_have_features")), bool(home.get("target_property_type"))]
    score += sum(2 for x in checks if x)
    score = max(0,min(100,score))

    label = "Ready to Buy" if score>=90 else "Ready Soon" if score>=80 else "Nearly Ready" if score>=70 else "Needs Preparation" if score>=60 else "Significant Preparation Needed" if score>=40 else "Early Planning Stage"

    max_ratio = n(prefs.get("maximum_payment_to_income_percent"),28)/100
    target_payment = gross_m*max_ratio
    lo, hi = 0.0, max(1_000_000.0, price*2)
    for _ in range(50):
        mid=(lo+hi)/2
        loan_mid=mid*(1-down_pct/100)
        cost=payment(loan_mid,rate,30)+mid*(tax_pct+ins_pct+maint_pct)/100/12+hoa
        if cost<=target_payment: lo=mid
        else: hi=mid

    return {"score":score,"label":label,"dti":dti,"cash_gap":cash_gap,"comfortable_price":lo}

def build_market_ranking(latest, sim_summary):
    rows=[]
    for _,r in latest.iterrows():
        m=r["market"]; s=sim_summary[sim_summary["market"]==m]
        if s.empty:
            neutral=buy=best_score=best_month=np.nan
        else:
            b=s.sort_values(["prob_slight_buy_or_better","prob_neutral_or_better","entry_score_mean"],ascending=False).iloc[0]
            neutral=b["prob_neutral_or_better"]; buy=b["prob_slight_buy_or_better"]; best_score=b["entry_score_mean"]; best_month=b["horizon_months"]
        entry=n(r.get("entry_score"),50); conf=n(r.get("forecast_confidence_score"),50); growth=n(r.get("predicted_12m_growth_pct")); aff=n(r.get("affordability_score"),50); risk=n(r.get("risk_score"),50)
        total=entry*.35+conf*.15+max(0,min(100,50+growth*5))*.15+aff*.15+(100-risk)*.10+n(neutral)*100*.10
        rows.append({"market":m,"market_ranking_score":total,"current_entry_score":entry,"current_signal":r.get("entry_signal",signal_strength(entry)),"predicted_12m_growth_pct":growth,"forecast_confidence_score":conf,"affordability_score":aff,"risk_score":risk,"best_simulated_entry_score":best_score,"best_simulated_window_months":best_month,"prob_neutral_or_better_at_best_window":neutral,"prob_slight_buy_or_better_at_best_window":buy})
    out=pd.DataFrame(rows).sort_values("market_ranking_score",ascending=False)
    out["market_rank"]=range(1,len(out)+1)
    return out

def build_financing_optimizer(profile, latest):
    if not profile: return pd.DataFrame()
    home=profile.get("home_purchase",{}); credit=profile.get("credit",{}); asm=profile.get("assumptions",{}); budget=profile.get("monthly_budget",{}); debt=profile.get("debts",{}); cash=profile.get("cash_assets",{})
    price=n(home.get("target_purchase_price"),350000); closing=n(home.get("estimated_closing_cost_percent"),3); cs=n(credit.get("credit_score"),700)
    tax=n(asm.get("property_tax_percent"),1.3); ins=n(asm.get("homeowners_insurance_percent"),0.4); maint=n(asm.get("expected_home_maintenance_percent"),1.0); hoa=n(asm.get("hoa_monthly"))
    gross=n(budget.get("gross_monthly_income")); monthly_debt=n(debt.get("monthly_debt_payments")); reserved=n(cash.get("cash_reserved_for_down_payment"))
    rows=[]
    for _,mr in latest.iterrows():
        market=mr["market"]; rate=n(mr.get("mortgage_30yr"),6.75)
        for term in [15,30]:
            for dp in [3,5,10,20]:
                loan=price*(1-dp/100); pi=payment(loan,rate,term)
                pmi=0 if dp>=20 else loan*(0.0035 if cs>=760 else 0.0045 if cs>=720 else 0.006 if cs>=680 else 0.008 if cs>=640 else 0.011)/12
                total=pi+pmi+price*(tax+ins+maint)/100/12+hoa
                dti=(total+monthly_debt)/gross if gross else np.nan
                cash_need=price*(dp+closing)/100; gap=max(0,cash_need-reserved); interest=pi*term*12-loan
                score=max(0,100-max(0,(dti-.36)*200 if pd.notna(dti) else 100)-min(40,gap/max(price,1)*100)-min(10,pmi/max(total,1)*50)-min(20,interest/max(price,1)*10))
                rows.append({"market":market,"term_years":term,"down_payment_percent":dp,"mortgage_rate":rate,"target_purchase_price":price,"loan_amount":loan,"monthly_principal_interest":pi,"monthly_pmi":pmi,"total_monthly_housing_cost":total,"back_end_dti":dti,"cash_needed_at_close":cash_need,"cash_gap":gap,"estimated_total_interest":interest,"financing_score":score})
    out=pd.DataFrame(rows); out["financing_rank_within_market"]=out.groupby("market")["financing_score"].rank(method="dense",ascending=False).astype(int)
    return out.sort_values(["market","financing_rank_within_market"])

def build_combined_score(latest, profile, ranking):
    target=n(profile.get("home_purchase",{}).get("target_purchase_price"),350000) if profile else 350000
    rows=[]
    for _,r in latest.iterrows():
        market=r["market"]; p=personal_score(profile,target,n(r.get("mortgage_30yr"),6.75)); rr=ranking[ranking["market"]==market]
        rank=n(rr.iloc[0]["market_ranking_score"],50) if not rr.empty else 50
        entry=n(r.get("entry_score"),50); conf=n(r.get("forecast_confidence_score"),50); ps=n(p["score"],0)
        combined=ps*.45+entry*.30+rank*.15+conf*.10
        rec="Ready to Act When Desired Property Appears" if combined>=80 else "Prepare to Buy Soon" if combined>=68 else "Monitor Market and Improve Readiness" if combined>=55 else "Wait and Strengthen Financial Position" if combined>=40 else "Early Preparation Stage"
        rows.append({"market":market,"market_entry_score":entry,"market_signal":r.get("entry_signal",signal_strength(entry)),"market_ranking_score":rank,"personal_readiness_score":ps,"personal_readiness_label":p["label"],"forecast_confidence_score":conf,"combined_purchase_readiness_score":combined,"overall_recommendation":rec,"comfortable_purchase_price":p["comfortable_price"],"profile_target_purchase_price":target,"estimated_back_end_dti":p["dti"],"cash_gap":p["cash_gap"]})
    return pd.DataFrame(rows).sort_values("combined_purchase_readiness_score",ascending=False)

def build_alerts(latest, monitoring, meaningful, timing_advice=True):
    rows=[]
    for _,r in latest.iterrows():
        market=r["market"]; score=n(r.get("entry_score"),50); signal=r.get("entry_signal",signal_strength(score))
        if score>=60: rows.append({"market":market,"severity":"High","alert_type":"Buy Signal","message":f"{market} is {signal} at {score:.1f}."})
        elif score>=48: rows.append({"market":market,"severity":"Medium","alert_type":"Fair Value","message":f"{market} has reached Neutral/Fair Value."})
    if monitoring is not None and not monitoring.empty:
        for _,r in monitoring.iterrows():
            market=r["market"]; sc=n(r.get("entry_score_change_since_last_run")); mc=n(r.get("mortgage_30yr_change_since_last_run")); fc=n(r.get("predicted_12m_growth_pct_change_since_last_run"))
            if "comparable_with_prior_run" in r.index and not bool(r["comparable_with_prior_run"]) and pd.notna(r["model_version_prior"]):
                rows.append({"market":market,"severity":"Informational","alert_type":"Model Version Change","message":f"{market}: the model changed from {r['model_version_prior']} to {r['model_version']} since the last run, so changes are not compared."})
            if abs(sc)>=3: rows.append({"market":market,"severity":"High","alert_type":"Entry Score Change","message":f"{market} entry score changed by {sc:+.1f}."})
            if abs(mc)>=.25:
                prior=n(r.get("mortgage_30yr_prior"),np.nan); now=n(r.get("mortgage_30yr"),np.nan)
                detail=f" ({prior:.2f}% to {now:.2f}%)" if prior==prior and now==now else ""
                rows.append({"market":market,"severity":"Medium","alert_type":"Mortgage Rate Change","message":f"Mortgage rate changed by {mc:+.2f} points{detail}."})
            if abs(fc)>=1: rows.append({"market":market,"severity":"Medium","alert_type":"Forecast Change","message":f"{market} forecast changed by {fc:+.1f} points."})
    if meaningful is not None and not meaningful.empty:
        for _,r in meaningful.iterrows():
            if timing_advice:
                rows.append({"market":r["market"],"severity":"Informational","alert_type":"Projected Opportunity Window","message":f"{r['market']} first meaningful improvement: {r['first_meaningful_window_label']}."})
            else:   # V11.1: scenario output, not timing advice (the Entry Score failed its timing test)
                rows.append({"market":r["market"],"severity":"Informational","alert_type":"Simulated Score Path","message":f"{r['market']}: the simulated Entry Score first improves meaningfully at {r['first_meaningful_window_label']}. This is scenario output, not timing advice."})
    return pd.DataFrame(rows)