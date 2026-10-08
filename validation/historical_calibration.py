from __future__ import annotations
import numpy as np
import pandas as pd
from scoring.entry_score import signal_strength

def build_historical_calibration(model_data):
    data=model_data.dropna(subset=["entry_score","target_4q_growth"]).copy()
    if data.empty: return pd.DataFrame(),pd.DataFrame()
    data["historical_signal"]=data["entry_score"].apply(signal_strength)
    rows=[]
    for (market,signal),g in data.groupby(["market","historical_signal"]):
        rows.append({"market":market,"historical_signal":signal,"observations":len(g),"mean_future_12m_growth":g["target_4q_growth"].mean(),"median_future_12m_growth":g["target_4q_growth"].median(),"future_growth_p10":g["target_4q_growth"].quantile(.1),"future_growth_p90":g["target_4q_growth"].quantile(.9),"decline_rate":(g["target_4q_growth"]<0).mean(),"prob_growth_above_3pct":(g["target_4q_growth"]>=.03).mean(),"prob_growth_above_5pct":(g["target_4q_growth"]>=.05).mean(),"average_entry_score":g["entry_score"].mean()})
    cal=pd.DataFrame(rows)
    diag=[]
    for market,g in data.groupby("market"):
        low=g[g["entry_score"]<48]; high=g[g["entry_score"]>=48]
        diag.append({"market":market,"observations":len(g),"entry_score_future_growth_correlation":g["entry_score"].corr(g["target_4q_growth"]),"entry_score_future_growth_rank_correlation":g["entry_score"].rank().corr(g["target_4q_growth"].rank()),"mean_growth_below_neutral":low["target_4q_growth"].mean() if not low.empty else np.nan,"mean_growth_neutral_or_better":high["target_4q_growth"].mean() if not high.empty else np.nan,"decline_rate_below_neutral":(low["target_4q_growth"]<0).mean() if not low.empty else np.nan,"decline_rate_neutral_or_better":(high["target_4q_growth"]<0).mean() if not high.empty else np.nan,"calibration_pass":bool(not low.empty and not high.empty and high["target_4q_growth"].mean()>=low["target_4q_growth"].mean())})
    return cal,pd.DataFrame(diag)