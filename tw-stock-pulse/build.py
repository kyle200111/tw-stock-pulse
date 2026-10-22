"""Taiwan Swing Pulse — official-source EOD screener. Python stdlib only.

Data limitations: listed equities only in V1; max top liquid universe; institutional and earnings
not historical in this implementation. Missing pillars are not silently awarded points.
"""
import json, os, time, math, statistics, datetime, urllib.request, urllib.parse, random
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
TZ=datetime.timezone(datetime.timedelta(hours=8))
NOW=datetime.datetime.now(TZ)
UA={'User-Agent':'Mozilla/5.0 (compatible; TaiwanSwingPulse/1.0; educational research)','Accept':'application/json'}

def read_json(path, fallback):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:return fallback

def fetch(url, retries=3):
    for n in range(retries):
        try:
            req=urllib.request.Request(url,headers=UA)
            with urllib.request.urlopen(req,timeout=28) as r:return json.load(r)
        except Exception as exc:
            print('fetch failed',n+1,url,str(exc)[:110]); time.sleep(1.6*(n+1))
    return None

def number(v):
    if isinstance(v,(int,float)):return float(v) if math.isfinite(v) else None
    try:
        v=str(v).replace(',','').strip().replace('＋','+').replace('−','-')
        if not v or v in ('--','-','---','N/A','X'):return None
        return float(v)
    except Exception:return None

def roc_date(s):
    s=str(s).strip()
    if '/' in s:
        pieces=s.split('/')
        try:return f'{int(pieces[0])+(1911 if int(pieces[0])<1900 else 0):04}-{int(pieces[1]):02}-{int(pieces[2]):02}'
        except Exception:return None
    if s.isdigit() and len(s)>=7:
        return f'{int(s[:-4])+1911:04}-{s[-4:-2]}-{s[-2:]}'
    return None

def load_latest():
    raw=fetch('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
    if not isinstance(raw,list):return []
    out=[]
    for r in raw:
        code=str(r.get('Code',''))
        if len(code)!=4 or not code.isdigit():continue
        close=number(r.get('ClosingPrice')); value=number(r.get('TradeValue'))
        if close is None or close<=0 or value is None:continue
        out.append({'ticker':code,'name':r.get('Name',''), 'close':close,'volume':number(r.get('TradeVolume')),'value':value,'date':roc_date(r.get('Date')),'market':'TWSE'})
    return out

def revenue_lookup():
    raw=fetch('https://openapi.twse.com.tw/v1/opendata/t187ap05_L')
    if not isinstance(raw,list):return {}
    out={}
    for r in raw:
        code=str(r.get('公司代號') or r.get('公司代碼') or '').strip()
        if len(code)!=4:continue
        yoy=number(r.get('營業收入-去年同月增減(%)') or r.get('營業收入-去年同月增減％') or r.get('去年同月增減(%)'))
        # Source keys may differ between versions; missing is unavailable, never presumed positive.
        out[code]={'yoy':yoy,'period':str(r.get('資料年月','')),'source':'TWSE t187ap05_L'}
    return out

def valuation_lookup():
    raw=fetch('https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL')
    if not isinstance(raw,list):return {}
    out={}
    for r in raw:
        code=str(r.get('Code') or r.get('證券代號') or '')
        if len(code)!=4:continue
        out[code]={'pe':number(r.get('PEratio') or r.get('本益比')),'pb':number(r.get('PBratio') or r.get('股價淨值比'))}
    return out

def institutional_5day():
    """Fetch the five most recent available TWSE T86 sessions, indexed by ticker.

    The official source returns shares, not lots. Do not assign scores if fewer
    than five sessions are available; holidays are handled by scanning weekdays.
    """
    session=[]
    cache=DATA/'institutions';cache.mkdir(exist_ok=True)
    for back in range(17):
        day=(NOW-datetime.timedelta(days=back)).date()
        if day.weekday()>4:continue
        key=day.strftime('%Y%m%d');path=cache/f'{key}.json'
        raw=read_json(path,None)
        if raw is None:
            url='https://www.twse.com.tw/rwd/zh/fund/T86?'+urllib.parse.urlencode({'date':key,'selectType':'ALLBUT0999','response':'json'})
            raw=fetch(url,2)
            if isinstance(raw,dict) and raw.get('stat')=='OK' and raw.get('data'):
                path.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
        if not isinstance(raw,dict) or raw.get('stat')!='OK':continue
        fields=raw.get('fields',[])
        def idx(key):
            for i,f in enumerate(fields):
                if key in str(f):return i
            return None
        code_i=idx('證券代號'); f_i=idx('外陸資買賣超股數(不含外資自營商)'); t_i=idx('投信買賣超股數')
        if None in (code_i,f_i,t_i):continue
        rows={}
        for row in raw.get('data',[]):
            try:
                code=str(row[code_i]).strip();foreign=number(row[f_i]);trust=number(row[t_i])
                if len(code)==4 and code.isdigit() and foreign is not None and trust is not None:rows[code]={'foreign':foreign,'trust':trust}
            except (IndexError,TypeError):continue
        if rows:session.append((day.isoformat(),rows))
        if len(session)>=5:break
    if len(session)<5:return {},len(session)
    codes=set.intersection(*(set(rows) for _,rows in session))
    out={code:{'foreign5':sum(rows[code]['foreign'] for _,rows in session),'trust5':sum(rows[code]['trust'] for _,rows in session),'through':session[0][0]} for code in codes}
    return out,5

def load_history(ticker, months=6):
    cache_file=DATA/'history'/f'{ticker}.json';cache_file.parent.mkdir(exist_ok=True)
    old=read_json(cache_file,{})
    dates=[]; year=NOW.year;month=NOW.month
    for k in range(months):
        y=year+(month-1-k)//12; m=(month-1-k)%12+1
        dates.append(f'{y}{m:02}01')
    for ym in reversed(dates):
        if ym in old:continue
        u='https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?'+urllib.parse.urlencode({'date':ym,'stockNo':ticker,'response':'json'})
        raw=fetch(u,2)
        rows=[]
        if isinstance(raw,dict) and raw.get('stat')=='OK':
            for values in raw.get('data',[]):
                if len(values)<7:continue
                date=roc_date(values[0]); close=number(values[6]); high=number(values[4]); low=number(values[5]);volume=number(values[1]); turnover=number(values[2]);
                if date and all(q is not None for q in (close,high,low,volume,turnover)):
                    rows.append({'date':date,'close':close,'high':high,'low':low,'volume':volume,'value':turnover})
        if rows:old[ym]=rows
        time.sleep(0.20)
    cache_file.write_text(json.dumps(old,ensure_ascii=False),encoding='utf-8')
    combined={r['date']:r for group in old.values() for r in group}
    return sorted(combined.values(),key=lambda r:r['date'])

def mean(seq):return sum(seq)/len(seq) if seq else None

def calc(s, hist, rev, val, inst=None):
    if len(hist)<65:return None
    closes=[r['close'] for r in hist]; highs=[r['high'] for r in hist]; lows=[r['low'] for r in hist]; vals=[r['value'] for r in hist]; vols=[r['volume'] for r in hist]
    price=closes[-1];ma20=mean(closes[-20:]);ma60=mean(closes[-60:]); avgv=mean(vals[-20:]); avgvol=mean(vols[-20:])
    if price<20 or avgv<50_000_000 or not(price>ma20>ma60):return None
    # Revenue strictly validated whenever present; data gap still shown explicitly.
    yoy=rev.get('yoy') if rev else None
    if yoy is not None and yoy<0:return None
    pe=val.get('pe') if val else None
    tr=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(len(hist)-14,len(hist))]
    atr=mean(tr)
    if atr is None or atr<=0:return None
    r20=price/closes[-21]-1;r60=price/closes[-61]-1
    vol_ratio=vols[-1]/avgvol if avgvol else 0
    hi20=max(highs[-21:-1]); entry='突破' if price>hi20 and vol_ratio>=1.5 else '回檔/觀察'
    # Only measured sub-scores counted; missing EPS and institutional trends remain explicitly unscored.
    fundamental=(12 if yoy is not None and yoy>=20 else (7 if yoy is not None and yoy>=0 else 0)) if yoy is not None else None # revenue subcomponent max 12; EPS subcomponent max 8 unavailable
    momentum=(10 if ma20>ma60 else 0)+(10 if r20>=0.07 else (6 if r20>0 else 0))+(10 if r60>=0.12 else (5 if r60>0 else 0))
    volume=(8 if avgv>=200_000_000 else 5)+(7 if vol_ratio>=1.5 else (4 if vol_ratio>=1 else 0))
    institution=None
    if inst and avgvol and avgvol>0:
        ratio=(inst['foreign5']+inst['trust5'])/(5*avgvol)
        institution=(8 if ratio>=0.10 else 5 if ratio>0 else 0)+(7 if inst['trust5']>0 else 0)
    valuation=(8 if pe is not None and 0<pe<=25 else (5 if pe is not None and pe<=40 else (1 if pe is not None and pe>0 else 0))) if pe is not None else None
    risk=10 if atr/price<0.035 else 6 if atr/price<0.06 else 3
    known=[momentum,volume,risk]; cap=30+15+10
    if fundamental is not None:known.append(fundamental);cap+=12
    if institution is not None:known.append(institution);cap+=15
    if valuation is not None:known.append(valuation);cap+=10
    # Full score intentionally withheld while institutional and earnings completeness not met.
    observed=sum(known);score=round(observed/cap*100,1)
    stop=round(max(0.01,price-2*atr),2)
    target=round(price+3*atr,2)
    weeks='2–4週' if r20>=.15 else '4–8週' if r20>=.05 else '6–12週'
    return {'ticker':s['ticker'],'name':s['name'],'market':'TWSE','date':hist[-1]['date'], 'price':round(price,2),'score':None,'observedScore':score,'scoreCoverage':cap,'scoreMaximum':100,'status':'研究候選｜分數不完整', 'holding':weeks,'target':target,'stop':stop,'entryType':entry,'upside':round((target/price-1)*100,1),'downside':round((stop/price-1)*100,1),'ma20':round(ma20,2),'ma60':round(ma60,2),'atr14':round(atr,2),'ret20':round(r20*100,1),'ret60':round(r60*100,1),'volumeRatio':round(vol_ratio,2),'avgValue20':round(avgv),'revenueYoy':yoy,'revenuePeriod':rev.get('period') if rev else None,'foreign5Shares':inst.get('foreign5') if inst else None,'trust5Shares':inst.get('trust5') if inst else None,'institutionalThrough':inst.get('through') if inst else None,'pe':pe,'missing':['近4季EPS未串接']+([] if institution is not None else ['法人最近五交易日資料缺失'])+(['估值資料缺失'] if valuation is None else [])+(['月營收年增缺失'] if yoy is None else []),'scoreParts':{'fundamental':fundamental,'momentum':momentum,'volume':volume,'institutional':institution,'valuation':valuation,'risk':risk},'rationale':['價位高於MA20、MA60且MA20>MA60',f'近20日報酬 {r20*100:.1f}%',f'ATR(14) {atr:.2f}'],'sourceUrls':['https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY','https://openapi.twse.com.tw/v1/opendata/t187ap05_L']}

def main():
    latest=load_latest()
    previous=read_json(DATA/'latest.json',{})
    if not latest:
        print('No official latest quote; retain prior publication with warning');
        previous['warning']='本次官方行情 API 讀取失敗；沿用歷史資料。';previous['attemptAt']=NOW.isoformat()
        (DATA/'latest.json').write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8');return
    # Need a bounded universe to respect official-service load; top 60 by latest traded value.
    liquid=sorted(latest,key=lambda z:z['value'],reverse=True)[:60]
    revenue=revenue_lookup();valuation=valuation_lookup();institutional,inst_sessions=institutional_5day()
    scored=[];errors=[]
    for i,s in enumerate(liquid):
        print(f'{i+1}/{len(liquid)} {s["ticker"]}',flush=True)
        h=load_history(s['ticker'])
        # guard against stale historical candles: latest quote can be more recent than cache
        if h and s['date'] and h[-1]['date']<s['date']:
            errors.append(f'{s["ticker"]}:歷史價格尚未涵蓋最新交易日')
            continue
        record=calc(s,h,revenue.get(s['ticker']),valuation.get(s['ticker']),institutional.get(s['ticker']))
        if record:scored.append(record)
    scored.sort(key=lambda x:(x['observedScore'],x['ret20']),reverse=True)
    payload={'updatedAt':NOW.isoformat(),'quoteDate':latest[0]['date'],'universe':'TWSE 成交金額前60名；非全市場','totalConsidered':len(liquid),'eligible':len(scored),'mode':'PARTIAL_DATA','institutionalSessions':inst_sessions,'method':'可得欄位的比例分數（不等於100分完整模型）','warning':'研究用途；本版尚缺完整近四季EPS；部分個股法人資料可能不足，故不顯示完整100分，也不將其當成正式買入訊號。','errors':errors[:12],'items':scored,'sources':[{'name':'上市當日行情','url':'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL'},{'name':'歷史日行情','url':'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY'},{'name':'月營收','url':'https://openapi.twse.com.tw/v1/opendata/t187ap05_L'},{'name':'本益比','url':'https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL'},{'name':'法人近五日','url':'https://www.twse.com.tw/rwd/zh/fund/T86'}]}
    (DATA/'latest.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'site'/'data.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    print('DONE',len(scored),'eligible,',len(errors),'stale')
if __name__=='__main__':main()
