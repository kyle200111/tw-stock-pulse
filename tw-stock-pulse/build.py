"""Taiwan Pulse v1.3: verified rolling EPS, 100-point score, date integrity.
Stdlib only. Sources: TWSE public endpoints; FinMind historical EPS (if API accessible).
Missing components NEVER silently receive full score.
"""
import datetime as dt
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
SITE = ROOT / 'site'
DATA.mkdir(exist_ok=True)
SITE.mkdir(exist_ok=True)
TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime.now(TZ)
USER_AGENT = {'User-Agent': 'Mozilla/5.0 (TaiwanPulse research screener)', 'Accept': 'application/json'}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def fetch(url, retries=2, headers=None):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={**USER_AGENT, **(headers or {})}), timeout=25) as res:
                return json.load(res)
        except Exception as exc:
            print('API error', attempt + 1, url.split('?')[0], str(exc)[:100], flush=True)
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    return None


def num(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        val = float(str(value).replace(',', '').replace('−', '-').strip())
        return val if math.isfinite(val) else None
    except (TypeError, ValueError):
        return None


def roc_date(text):
    text = str(text or '').strip()
    try:
        if '/' in text:
            y, m, d = map(int, text.split('/'))
            return dt.date(y + (1911 if y < 1900 else 0), m, d).isoformat()
        if '-' in text:
            return dt.date.fromisoformat(text[:10]).isoformat()
        if text.isdigit() and len(text) in (7, 8):
            y = int(text[:-4]); m = int(text[-4:-2]); d = int(text[-2:])
            return dt.date(y + (1911 if y < 1900 else 0), m, d).isoformat()
    except ValueError:
        pass
    return None


def latest_quotes():
    raw = fetch('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
    stocks = []
    if not isinstance(raw, list):
        return stocks
    for row in raw:
        ticker = str(row.get('Code', '')).strip()
        price, value = num(row.get('ClosingPrice')), num(row.get('TradeValue'))
        if not (len(ticker) == 4 and ticker.isdigit() and price and price > 0 and value and value > 0):
            continue
        stocks.append({'ticker': ticker, 'name': row.get('Name', ''), 'value': value,
                       'price': price, 'date': roc_date(row.get('Date'))})
    return stocks


def revenue_data():
    raw = fetch('https://openapi.twse.com.tw/v1/opendata/t187ap05_L')
    out = {}
    for row in raw if isinstance(raw, list) else []:
        code = str(row.get('公司代號') or row.get('公司代碼') or '').strip()
        yoy = next((num(row.get(k)) for k in ['營業收入-去年同月增減(%)', '營業收入-去年同月增減％', '去年同月增減(%)'] if num(row.get(k)) is not None), None)
        if len(code) == 4:
            out[code] = {'yoy': yoy, 'period': str(row.get('資料年月', ''))}
    return out


def valuations():
    raw = fetch('https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL')
    out = {}
    for row in raw if isinstance(raw, list) else []:
        code = str(row.get('Code') or row.get('證券代號') or '').strip()
        if len(code) == 4:
            out[code] = {'pe': num(row.get('PEratio') or row.get('本益比'))}
    return out


def institutions():
    sessions = []
    for days_back in range(17):
        day = NOW.date() - dt.timedelta(days=days_back)
        if day.weekday() >= 5:
            continue
        key = day.strftime('%Y%m%d')
        path = DATA / 'institutions' / f'{key}.json'
        raw = read(path)
        if raw is None:
            url = 'https://www.twse.com.tw/rwd/zh/fund/T86?' + urllib.parse.urlencode({'date': key, 'selectType': 'ALLBUT0999', 'response': 'json'})
            raw = fetch(url, retries=1)
            if isinstance(raw, dict) and raw.get('stat') == 'OK' and raw.get('data'):
                save(path, raw)
        if not isinstance(raw, dict) or raw.get('stat') != 'OK':
            continue
        fields = [str(f) for f in raw.get('fields', [])]
        def index(fragment):
            return next((i for i, name in enumerate(fields) if fragment in name), None)
        ci, fi, ti = index('證券代號'), index('外陸資買賣超股數(不含外資自營商)'), index('投信買賣超股數')
        if None in (ci, fi, ti):
            continue
        rows = {}
        for r in raw.get('data', []):
            if len(r) <= max(ci, fi, ti):
                continue
            code, foreign, trust = str(r[ci]).strip(), num(r[fi]), num(r[ti])
            if len(code) == 4 and code.isdigit() and foreign is not None and trust is not None:
                rows[code] = (foreign, trust)
        if rows:
            sessions.append((day.isoformat(), rows))
        if len(sessions) == 5:
            break
    if len(sessions) < 5:
        return {}, len(sessions)
    shared = set.intersection(*(set(rows) for _, rows in sessions))
    return {code: {'foreign5': sum(s[code][0] for _, s in sessions),
                   'trust5': sum(s[code][1] for _, s in sessions), 'through': sessions[0][0]} for code in shared}, 5


def history(ticker, months=7):
    path = DATA / 'history' / f'{ticker}.json'
    previous = read(path, {}) or {}
    dates = []
    for back in range(months):
        n = (NOW.year * 12 + NOW.month - 1) - back
        y, m = divmod(n, 12)
        dates.append(f'{y}{m + 1:02}01')
    # Recheck current calendar month on every run, since it grows trading-day by trading-day.
    current = f'{NOW.year}{NOW.month:02}01'
    for yearmonth in reversed(dates):
        if yearmonth in previous and yearmonth != current:
            continue
        url = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?' + urllib.parse.urlencode({'date': yearmonth, 'stockNo': ticker, 'response': 'json'})
        raw = fetch(url, retries=2)
        if isinstance(raw, dict) and raw.get('stat') == 'OK':
            parsed = []
            for r in raw.get('data', []):
                if len(r) < 7:
                    continue
                d, close, high, low, volume, value = roc_date(r[0]), num(r[6]), num(r[4]), num(r[5]), num(r[1]), num(r[2])
                if d and all(x is not None for x in (close, high, low, volume, value)):
                    parsed.append({'date': d, 'close': close, 'high': high, 'low': low, 'volume': volume, 'value': value})
            if parsed:
                previous[yearmonth] = parsed
        time.sleep(0.12)
    save(path, previous)
    merged = {r['date']: r for rows in previous.values() for r in rows}
    return sorted(merged.values(), key=lambda x: x['date'])


def validated_eps_ttm(rows, as_of_date):
    """FinMind EPS is *single-quarter*; require four consecutive quarters and known publication cutoff.
    Public endpoint does not supply point-in-time report dates: a conservative generic disclosure
    delay is applied, and historical backtesting must not use this approximation as PIT truth.
    Corporate-action retrospective EPS adjustment cannot be verified automatically here.
    """
    quarters = {}
    for row in rows:
        if row.get('type') != 'EPS':
            continue
        date = str(row.get('date') or '')[:10]
        try:
            qdate = dt.date.fromisoformat(date)
            if qdate.month not in (3, 6, 9, 12) or (qdate.month, qdate.day) not in ((3, 31), (6, 30), (9, 30), (12, 31)):
                continue
            # Conservative eligibility; exact company publication timestamp unknown.
            embargo = 75 if qdate.month == 12 else 60
            if qdate + dt.timedelta(days=embargo) > as_of_date:
                continue
            value = num(row.get('value'))
            if value is not None:
                quarters[(qdate.year, (qdate.month - 1) // 3 + 1)] = (value, date)
        except ValueError:
            continue
    if not quarters:
        return None
    keys = sorted(quarters)[-4:]
    if len(keys) != 4:
        return None
    ordinal = [year * 4 + q for year, q in keys]
    if any(b - a != 1 for a, b in zip(ordinal, ordinal[1:])):
        return None
    return {'value': round(sum(quarters[k][0] for k in keys), 3), 'quarters': [quarters[k][1] for k in keys],
            'source': 'FinMind/TaiwanStockFinancialStatements', 'basis': '原始單季EPS四季加總（未校正配股與分割）',
            'corporateActionVerified': False}


def verify_eps_corporate_actions(ticker, eps):
    """Conservatively validate against known stock dividends and split events.
    An empty successful dataset is valid; failed API requests cannot certify.
    Note: full IAS 33 retroactive reconciliation remains an external audit task.
    """
    if not eps:
        return None
    start = eps['quarters'][0]
    token = os.environ.get('FINMIND_TOKEN', '').strip()
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    datasets = ('TaiwanStockDividend', 'TaiwanStockSplitPrice')
    results = []
    for dataset in datasets:
        url = 'https://api.finmindtrade.com/api/v4/data?' + urllib.parse.urlencode({
            'dataset': dataset, 'data_id': ticker, 'start_date': start})
        raw = fetch(url, retries=1, headers=headers)
        if not isinstance(raw, dict) or not isinstance(raw.get('data'), list):
            return eps
        results.append(raw['data'])
    # These flags are approximate and cannot guarantee all IFRS retroactive share adjustments.
    stock_dividends = any((num(row.get('StockEarningsDistribution')) or 0) != 0 for row in results[0])
    split_events = bool(results[1])
    eps['corporateActionChecked'] = True
    eps['corporateActionRisk'] = stock_dividends or split_events
    # Do not promote to audited score based solely on public event absence.
    return eps


def eps_history(ticker, as_of_date):
    path = DATA / 'earnings' / f'{ticker}.json'
    cached = read(path, {}) or {}
    # Cache one day to protect provider quota; no data falsely promoted to complete TTM.
    if cached.get('fetchedDate') == NOW.date().isoformat():
        return verify_eps_corporate_actions(ticker, validated_eps_ttm(cached.get('rows', []), as_of_date))
    since = (as_of_date - dt.timedelta(days=730)).isoformat()
    url = 'https://api.finmindtrade.com/api/v4/data?' + urllib.parse.urlencode({
        'dataset': 'TaiwanStockFinancialStatements', 'data_id': ticker, 'start_date': since})
    token = os.environ.get('FINMIND_TOKEN', '').strip()
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    raw = fetch(url, retries=1, headers=headers)
    if isinstance(raw, dict) and isinstance(raw.get('data'), list):
        filtered = [r for r in raw['data'] if r.get('type') == 'EPS']
        if filtered:
            save(path, {'fetchedDate': NOW.date().isoformat(), 'rows': filtered})
            return verify_eps_corporate_actions(ticker, validated_eps_ttm(filtered, as_of_date))
    return verify_eps_corporate_actions(ticker, validated_eps_ttm(cached.get('rows', []), as_of_date))


def score_stock(s, bars, rev, valuation, institution, eps):
    if len(bars) < 65 or not s.get('date') or bars[-1]['date'] != s['date']:
        return None, '行情日期與價格歷史不一致'
    c = [r['close'] for r in bars]
    high, low = [r['high'] for r in bars], [r['low'] for r in bars]
    volume, values = [r['volume'] for r in bars], [r['value'] for r in bars]
    price, ma20, ma60 = c[-1], statistics.mean(c[-20:]), statistics.mean(c[-60:])
    avg_volume, avg_value = statistics.mean(volume[-20:]), statistics.mean(values[-20:])
    yoy = rev.get('yoy') if rev else None
    if price < 20 or avg_value < 50_000_000 or not (price > ma20 > ma60) or (yoy is not None and yoy < 0):
        return None, None
    tr = [max(high[i] - low[i], abs(high[i] - c[i - 1]), abs(low[i] - c[i - 1])) for i in range(len(bars) - 14, len(bars))]
    atr = statistics.mean(tr)
    if atr <= 0:
        return None, None
    ret20, ret60 = price / c[-21] - 1, price / c[-61] - 1
    volratio = volume[-1] / avg_volume if avg_volume else 0
    pe = valuation.get('pe') if valuation else None
    parts = {}
    # Fundamental out of 20: revenue 12, EPS 8. No EPS points until quarter history is present.
    revenue_pts = 12 if yoy is not None and yoy >= 20 else 7 if yoy is not None and yoy >= 0 else 0
    eps_pts = 8 if eps and eps['value'] > 0 else 0
    parts['fundamental'] = revenue_pts + eps_pts if yoy is not None and eps else None
    parts['momentum'] = (10 if ma20 > ma60 else 0) + (10 if ret20 >= .07 else 6 if ret20 > 0 else 0) + (10 if ret60 >= .12 else 5 if ret60 > 0 else 0)
    parts['volume'] = (8 if avg_value >= 200_000_000 else 5) + (7 if volratio >= 1.5 else 4 if volratio >= 1 else 0)
    if institution and avg_volume:
        ratio = (institution['foreign5'] + institution['trust5']) / (5 * avg_volume)
        parts['institutional'] = (8 if ratio >= .10 else 5 if ratio > 0 else 0) + (7 if institution['trust5'] > 0 else 0)
    else:
        parts['institutional'] = None
    parts['valuation'] = (8 if 0 < pe <= 25 else 5 if 0 < pe <= 40 else 1 if pe and pe > 0 else 0) if pe is not None else None
    parts['risk'] = 10 if atr / price < .035 else 6 if atr / price < .06 else 3
    caps = {'fundamental': 20, 'momentum': 30, 'volume': 15, 'institutional': 15, 'valuation': 10, 'risk': 10}
    coverage = sum(caps[key] for key, value in parts.items() if value is not None)
    observed = sum(v for v in parts.values() if v is not None)
    # Need independently verified corporate action to label EPS as fully audited 100-point score.
    eps_verified = bool(eps and eps.get('corporateActionVerified'))
    fully_scored = coverage == 100 and eps_verified
    score = observed if fully_scored else None
    missing = []
    if not eps:
        missing.append('近四季EPS歷史資料不足')
    elif not eps_verified:
        missing.append('EPS配股/分割追溯調整尚未驗證')
    if yoy is None:
        missing.append('月營收年增資料缺失')
    if parts['institutional'] is None:
        missing.append('近5日法人籌碼缺失')
    if pe is None:
        missing.append('估值資料缺失')
    target, stop = round(price + 3 * atr, 2), round(max(.01, price - 2 * atr), 2)
    return {'ticker': s['ticker'], 'name': s['name'], 'market': 'TWSE', 'date': s['date'],
            'price': round(price, 2), 'score': score, 'observedScore': round(observed / coverage * 100, 1) if coverage else None,
            'scoreCoverage': coverage, 'scoreMaximum': 100,
            'status': '已完整評分' if fully_scored else '研究候選｜分數不完整',
            'holding': '2–4週' if ret20 >= .15 else '4–8週' if ret20 >= .05 else '6–12週',
            'target': target, 'stop': stop, 'upside': round((target / price - 1) * 100, 1),
            'downside': round((stop / price - 1) * 100, 1), 'ma20': round(ma20, 2), 'ma60': round(ma60, 2),
            'atr14': round(atr, 2), 'ret20': round(ret20 * 100, 1), 'ret60': round(ret60 * 100, 1),
            'volumeRatio': round(volratio, 2), 'avgValue20': round(avg_value), 'revenueYoy': yoy,
            'revenuePeriod': rev.get('period') if rev else None, 'foreign5Shares': institution.get('foreign5') if institution else None,
            'trust5Shares': institution.get('trust5') if institution else None,
            'institutionalThrough': institution.get('through') if institution else None,
            'pe': pe, 'epsTtm': eps.get('value') if eps else None,
            'epsQuarters': eps.get('quarters') if eps else None,
            'epsBasis': eps.get('basis') if eps else None, 'epsCorporateActionVerified': eps_verified,
            'missing': missing, 'scoreParts': parts,
            'rationale': ['價位高於MA20、MA60且MA20>MA60', f'近20日報酬 {ret20 * 100:.1f}%', f'ATR(14) {atr:.2f}']}, None


def main():
    quotes = latest_quotes()
    if not quotes:
        print('Latest market feed missing. Keeping prior website snapshot.', flush=True)
        return
    # Quote snapshot can have dates spanning multiple days when certain stocks are suspended.
    dated = [q for q in quotes if q['date']]
    if not dated:
        print('Missing market dates; do not publish unreliable data', flush=True)
        return
    anchor = max(q['date'] for q in dated)
    universe = sorted([q for q in dated if q['date'] == anchor], key=lambda x: x['value'], reverse=True)[:60]
    revenues, val, inst = revenue_data(), valuations(), None
    inst, sessions = institutions()
    results, errors = [], []
    for i, quote in enumerate(universe):
        print(f'{i + 1}/{len(universe)} {quote["ticker"]}', flush=True)
        bars = history(quote['ticker'])
        eps = eps_history(quote['ticker'], dt.date.fromisoformat(anchor)) if len(bars) >= 65 else None
        record, error = score_stock(quote, bars, revenues.get(quote['ticker']), val.get(quote['ticker']), inst.get(quote['ticker']), eps)
        if record:
            results.append(record)
        elif error:
            errors.append(f'{quote["ticker"]}: {error}')
    results.sort(key=lambda r: (r['observedScore'] or -1, r['ret20']), reverse=True)
    payload = {'updatedAt': NOW.isoformat(), 'quoteDate': anchor, 'universe': 'TWSE當日成交金額前60名',
               'totalConsidered': len(universe), 'eligible': len(results), 'institutionalSessions': sessions,
               'mode': 'COMPLETE' if results and all(r['score'] is not None for r in results) else 'PARTIAL_DATA',
               'method': '已驗證欄位相對分數；只有EPS股本調整驗證通過才會顯示100分完整評級',
               'warning': 'FinMind EPS為原始單季值。配股/分割可能使四季加總不一致；尚無企業行動校驗時僅能列研究候選，不標示正式完整評分。',
               'errors': errors[:20], 'items': results,
               'sources': [{'name': 'TWSE行情', 'url': 'https://openapi.twse.com.tw/'},
                           {'name': 'FinMind季EPS', 'url': 'https://finmind.github.io/tutor/TaiwanMarket/Fundamental/'}]}
    save(DATA / 'latest.json', payload)
    save(SITE / 'data.json', payload)
    print('Published', len(results), 'candidates; anchor', anchor, 'errors', len(errors), flush=True)


if __name__ == '__main__':
    main()
