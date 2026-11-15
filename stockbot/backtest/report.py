import pickle, numpy as np, sys, json, math
sys.path.insert(0,'.')
import engine as E
R=pickle.load(open('stage1.pkl','rb'))
K0, ND, CAL = E.K0, E.ND, E.CAL
k10 = next(i for i,d in enumerate(CAL) if d>='2010-01-04')
BUD={'swing':2500,'breakout':2500,'momentum':2500,'trend':2500,'tqqq':1000}
def rebal(parts, k0=K0):
    """Money split by the bot's budgets, reset to that split on the first trading day of each year."""
    eq=np.zeros(ND); tot=sum(BUD.values()); eq[k0]=tot
    w={n: BUD[n]/tot*tot for n in BUD}
    hold={n: BUD[n] for n in BUD}
    for k in range(k0+1, ND):
        for n in BUD:
            hold[n]*= parts[n][k]/parts[n][k-1]
        v=sum(hold.values()); eq[k]=v
        if CAL[k][:4]!=CAL[k-1][:4]:
            hold={n: v*BUD[n]/tot for n in BUD}
    return eq
spy=E.bench('SPY')*11000; qqq=E.bench('QQQ')*11000
out={}
for label in ('top30','all500','todays30'):
    parts={'swing':R['runs'][label]['swing']['eq'],'breakout':R['runs'][label]['breakout']['eq'],**R['etf']}
    eq=rebal(parts); out[label]=eq
    for nm,k0 in (('2000-2026',K0),('2010-2026',k10)):
        e2=rebal(parts,k0) if k0!=K0 else eq
        s=E.stats(e2,k0)
        print('%-9s %s  $11,000 -> $%s  %.1f%%/yr  maxDD %.1f%% (%s)  worst yr %s %.0f%%  up %d/%d  sharpe %.2f' % (label,nm,format(e2[-1],',.0f'),s['cagr'],s['maxdd'],s['dd_day'],s['worst_year'][0],s['worst_year'][1]*100,s['up_years'],s['years'],s['sharpe']))
for nm,k0 in (('2000-2026',K0),('2010-2026',k10)):
    s=E.stats(spy,k0); print('SPY       %s  x%.2f  %.1f%%/yr  maxDD %.1f%%  worst yr %s %.0f%%  up %d/%d sharpe %.2f'%(nm,s['x'],s['cagr'],s['maxdd'],s['worst_year'][0],s['worst_year'][1]*100,s['up_years'],s['years'],s['sharpe']))
print()
print('per strategy: 2000-2026 | 2010-2026')
for n in BUD:
    for label in (('top30','all500','todays30') if n in ('swing','breakout') else ('-',)):
        eq = R['runs'][label][n]['eq'] if label!='-' else R['etf'][n]
        a,b=E.stats(eq),E.stats(eq,k10)
        print('  %-9s %-9s %5.1f%%/yr DD %5.1f%%  | %5.1f%%/yr DD %5.1f%%' % (n,label,a['cagr'],a['maxdd'],b['cagr'],b['maxdd']))
# swing 2001 sanity
st=R['runs']['top30']['swing']
for y in ('2001','2008','2013','2021'):
    tr=[t for t in st['trades'] if t['out'][:4]==y]
    eq0=st['eq'][next(i for i,d in enumerate(CAL) if d[:4]==y)]
    print('swing top30', y, 'trades', len(tr), 'win %.0f%%'%(100*sum(t['usd']>0 for t in tr)/len(tr)), 'sumR %.1f'%sum(t['r'] for t in tr), 'sum$ %.0f'%sum(t['usd'] for t in tr), 'start eq %.0f'%eq0, 'avg loss per losing trade as %% of eq: %.2f'%(100*np.mean([t['usd'] for t in tr if t['usd']<=0])/eq0))
# yearly table for the chart
yrs=sorted({d[:4] for d in CAL[K0:]})
def ends(eq): 
    o=[]
    for y in yrs:
        ks=[k for k in range(K0,ND) if CAL[k][:4]==y]; o.append(round(float(eq[ks[-1]])))
    return o
json.dump({'years':yrs,'bot':ends(out['top30']),'bot_all':ends(out['all500']),'bot_biased':ends(out['todays30']),'spy':ends(spy)}, open('yearly.json','w'))
print(json.load(open('yearly.json')))
s1,s2=E.stats(out['top30']),E.stats(spy)
print('year by year bot vs spy:', ' '.join('%s:%+.0f/%+.0f'%(y,s1['by_year'][y]*100,s2['by_year'][y]*100) for y in yrs))
print('years bot beat SPY:', sum(s1['by_year'][y]>s2['by_year'][y] for y in yrs), 'of', len(yrs))
# time in market for swing
