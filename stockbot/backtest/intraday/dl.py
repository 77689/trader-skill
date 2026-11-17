import sys, os, urllib.request, urllib.parse, concurrent.futures as cf
FILES = [
 ("Maxim37/timeseries-1m-QQQ-10y","data/train-00000-of-00001.parquet","qqq10y.parquet"),
 ("Maxim37/timeseries-1m-QQQ-10y","README.md","qqq10y_README.md"),
 ("gpstathis/QQQ","QQQ_1m.csv","gp_QQQ_1m.csv"),
 ("gpstathis/QQQ","QQQ_1m_ext.csv","gp_QQQ_1m_ext.csv"),
 ("gpstathis/QQQ","README.md","gp_README.md"),
 ("Khanhpham1992/es-futures-1m","es_continuous_1m.parquet","es_1m.parquet"),
 ("sujalgawas/trade-1min-stock-5-yrs","data/train-00000-of-00002.parquet","stk5y_0.parquet"),
 ("sujalgawas/trade-1min-stock-5-yrs","data/train-00001-of-00002.parquet","stk5y_1.parquet"),
 ("sujalgawas/trade-1min-stock-5-yrs","README.md","stk5y_README.md"),
 ("deerfieldgreen/stk-intraday-data-1min","data/train-00000-of-00001.parquet","dfg_1min.parquet"),
 ("deerfieldgreen/stk-intraday-data-1min","README.md","dfg_1min_README.md"),
 ("deerfieldgreen/stk-intraday-data-5min","data/train-00000-of-00001.parquet","dfg_5min.parquet"),
 ("mdelcristo/NQ-F_1min_OHLCV_Parquet","README.md","nq_README.md"),
] + [("mdelcristo/NQ-F_1min_OHLCV_Parquet",f"NQ_1min_{y}.parquet",f"nq_{y}.parquet") for y in range(2015,2026)]
def get(a):
    repo,path,out=a; out=os.path.join('raw',out)  # prep.py reads raw/
    if os.path.exists(out) and os.path.getsize(out)>0: return out,'cached'
    url=f"https://huggingface.co/datasets/{repo}/resolve/main/{urllib.parse.quote(path)}"
    for k in range(4):
        try:
            urllib.request.urlretrieve(url,out+'.part'); os.replace(out+'.part',out); return out,os.path.getsize(out)
        except Exception as e: err=repr(e)
    return out,'FAIL '+err
os.makedirs('raw',exist_ok=True)
with cf.ThreadPoolExecutor(6) as ex:
    for o,s in ex.map(get,FILES): print(o,s,flush=True)
