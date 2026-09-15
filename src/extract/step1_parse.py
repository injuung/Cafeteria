# -*- coding: utf-8 -*-
# 이 모듈은 단독 실행용 파이프라인 단계다.
#   python -m src.extract.step1_parse
# 경로는 src/config/paths.py 한 곳에서만 정의한다.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from src.config import paths
paths.ensure_dirs()
_KR = str(paths.DATA_DIR)
_SRC = str(paths.DATA_DIR)

# -*- coding: utf-8 -*-
"""STEP1: 14개월치 생산일지/레시피북 원천 파싱 → /tmp/kr/raw.json"""
import openpyxl, re, glob, json, collections, datetime, os

ROOT = str(paths.DATA_DIR)
OUT = _KR
os.makedirs(OUT, exist_ok=True)

files = sorted(glob.glob(f'{ROOT}/생산일지/**/*.xlsx', recursive=True))

# ---------- 자리(slot) 정규화 ----------
SLOT_MAP = {
    '밥': '밥', '국': '국', '메인': '메인',
    '반찬1': '서브1', '반찬2': '서브2', '반찬3': '김치',
    '반찬4': '서브2', '보존식': None, '특식': None,
}
def slot_of(v):
    if not v: return None
    s = re.sub(r'\s+', '', str(v))
    return SLOT_MAP.get(s)

# ---------- 라인(공급처) 정규화 ----------
def line_of(v):
    if not v: return None
    s = re.sub(r'\s+', '', str(v))
    if s.startswith('중식'): return '유아'
    if '글로벌' in s or '석식' in s: return '성인'
    return s[:12]

records = []          # 일자별 편성 기록
date_errors = []      # A3 날짜 입력오류
slot_on_side = []     # 보조에 자리가 배정돼 있던 원본 케이스
sheet_src = {}        # (date,line,slot,name) 출처 추적
recipe_text = collections.defaultdict(collections.Counter)  # 품명 -> 자재사용내역 Counter
allergy_txt = collections.defaultdict(collections.Counter)  # 품명 -> 알레르기 Counter
weights     = collections.defaultdict(collections.Counter)  # 품명 -> 중량
memo_txt    = collections.defaultdict(collections.Counter)
ea_cnt      = collections.Counter()
occ_cnt     = collections.Counter()

for p in files:
    yr = p.split('/')[-2][:4]
    mo = p.split('/')[-1][:2]
    wb = openpyxl.load_workbook(p, data_only=True)

    for sn in wb.sheetnames:
        # --- 일자별 시트 ---
        if re.match(r'^\d\d-\d\d', sn):
            ws = wb[sn]
            # A3 셀 부근에 실제 날짜가 들어있음. 헤더행에서 날짜 추출
            date = None
            for r in ws.iter_rows(min_row=1, max_row=3, values_only=True):
                for v in r:
                    if hasattr(v, 'year'):
                        date = v.date(); break
                    if isinstance(v, str):
                        m = re.match(r'(\d{4})-(\d\d)-(\d\d)', v.strip())
                        if m:
                            date = datetime.date(*map(int, m.groups())); break
                if date: break
            # A3 날짜가 파일의 연/월과 어긋나면 시트명(월-일) + 파일 연도로 교정
            mm, dd = sn[:2], sn[3:5]
            try: sheet_date = datetime.date(int(yr), int(mm), int(dd))
            except Exception: sheet_date = None
            if date is None:
                if sheet_date is None: continue
                date = sheet_date
            elif date.strftime('%Y-%m') != f'{yr}-{mo}':
                date_errors.append({'file': f'{yr}년 {mo}월', 'sheet': sn,
                                    'cell_date': date.isoformat(),
                                    'fixed_to': sheet_date.isoformat() if sheet_date else ''})
                if sheet_date: date = sheet_date

            cur_line = None
            for r in ws.iter_rows(min_row=3, max_col=13, values_only=True):
                # B..L = idx1..11 : 출고일,구분(라인),구분(자리),품명,중량,수량,자재,알러지,배송,인원,총생산,메모
                lg = r[1]; sl = r[2]; name = r[3]; g = r[4]; ea = r[5]
                mat = r[6]; alg = r[7]; ppl = r[9]; memo = r[11]
                if lg: cur_line = line_of(lg)
                if not name: continue
                name = str(name).strip()
                if not name or name in ('0',): continue
                occ_cnt[name] += 1
                if mat: recipe_text[name][str(mat).strip()] += 1
                if alg not in (None, ''): allergy_txt[name][str(alg).strip()] += 1
                if isinstance(g, (int, float)) and g: weights[name][g] += 1
                if ea not in (None, 0, ''): ea_cnt[name] += 1
                if memo and str(memo).strip() not in ('0', ''):
                    memo_txt[name][str(memo).strip()] += 1
                s = slot_of(sl)
                if name.startswith('&') and s:
                    slot_on_side.append({'date': date.isoformat(), 'line': cur_line,
                                         'slot': s, 'name': name})
                    s = None          # 보조는 자리를 차지하지 않는다
                records.append({
                    'date': date.isoformat(), 'ym': f'{yr}-{mo}',
                    'line': cur_line, 'slot': s, 'name': name,
                    'g': g if isinstance(g, (int, float)) else None,
                    'ppl': ppl if isinstance(ppl, (int, float)) else None,
                })

        # --- 레시피북 / 온라인_반찬 ---
        elif sn in ('레시피북', '온라인_반찬'):
            ws = wb[sn]
            for r in ws.iter_rows(min_row=2, values_only=True):
                if len(r) > 8 and r[2]:
                    nm = str(r[2]).strip()
                    if r[7]: recipe_text[nm][str(r[7]).strip()] += 1
                    if r[8] not in (None, ''): allergy_txt[nm][str(r[8]).strip()] += 1
                    if isinstance(r[3], (int, float)) and r[3]: weights[nm][r[3]] += 1
                    if len(r) > 9 and r[9] and str(r[9]).strip() not in ('0', ''):
                        memo_txt[nm][str(r[9]).strip()] += 1

        # --- 급식_반찬 (보조) ---
        elif sn == '급식_반찬':
            ws = wb[sn]
            for r in ws.iter_rows(min_row=2, values_only=True):
                if len(r) > 4 and r[2]:
                    nm = str(r[2]).strip()
                    if r[4]: recipe_text[nm][str(r[4]).strip()] += 1

# 최신 레시피북 등재 목록
p9 = f'{ROOT}/생산일지/2026년/09월 생산일지.xlsx'
wb9 = openpyxl.load_workbook(p9, data_only=True)
book_latest = [str(r[2]).strip() for r in wb9['레시피북'].iter_rows(min_row=2, values_only=True) if r[2]]

# 식단표 파일 (유아/성인 대조용) - 생산일지 내 식단표 시트에서 추출
def grid(ws):
    out = {}
    rows = list(ws.iter_rows(values_only=True))
    for i, r in enumerate(rows):
        if r and r[0] and str(r[0]).strip() == '날짜':
            dates = {c: v.date() for c, v in enumerate(r) if hasattr(v, 'year')}
            for j in range(i + 1, min(i + 12, len(rows))):
                rr = rows[j]
                if rr and rr[0] and str(rr[0]).strip() == '날짜': break
                if rr and rr[0] and str(rr[0]).strip() == '주차': continue
                for c, d in dates.items():
                    v = rr[c] if c < len(rr) else None
                    if isinstance(v, str) and v.strip():
                        out.setdefault(d.isoformat(), []).append(v.strip())
    return out

kid_adult = []
for p in files:
    wb = openpyxl.load_workbook(p, data_only=True)
    ks = [s for s in wb.sheetnames if '유아' in s]
    as_ = [s for s in wb.sheetnames if '석식' in s or '글로벌' in s]
    if not ks or not as_: continue
    k, a = grid(wb[ks[0]]), grid(wb[as_[0]])
    for d in sorted(set(k) & set(a)):
        kid_adult.append({'date': d, 'kid': k[d], 'adult': a[d]})

# ---------- 중복 레코드 제거 (같은 날 동일 시트가 복제된 경우) ----------
_seen = set(); _dedup = []; dup_records = []
for r in records:
    k = (r['date'], r['line'], r['slot'], r['name'])
    if k in _seen:
        dup_records.append(r); continue
    _seen.add(k); _dedup.append(r)
records = _dedup

json.dump({
    'records': records,
    'dup_records': dup_records,
    'recipe_text': {k: v.most_common() for k, v in recipe_text.items()},
    'allergy_txt': {k: v.most_common() for k, v in allergy_txt.items()},
    'weights': {k: v.most_common() for k, v in weights.items()},
    'memo_txt': {k: v.most_common() for k, v in memo_txt.items()},
    'ea_cnt': dict(ea_cnt), 'occ_cnt': dict(occ_cnt),
    'book_latest': book_latest,
    'kid_adult': kid_adult,
    'date_errors': date_errors,
    'slot_on_side': slot_on_side,
}, open(f'{OUT}/raw.json', 'w'), ensure_ascii=False)

print('A3 날짜 입력오류(교정됨):', date_errors)
print('중복 제거:', len(dup_records), '건')
print('보조에 자리 배정돼 있던 원본:', slot_on_side)
print('편성 기록:', len(records))
print('고유 메뉴명:', len(occ_cnt))
print('자재내역 보유 메뉴:', len(recipe_text))
print('최신 레시피북:', len(book_latest))
print('유아/성인 동일날짜 대조 가능일:', len(kid_adult))
print('자리 분포:', collections.Counter(r['slot'] for r in records).most_common())
print('라인 분포:', collections.Counter(r['line'] for r in records).most_common(8))
