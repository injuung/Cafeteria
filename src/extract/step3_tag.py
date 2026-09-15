# -*- coding: utf-8 -*-
# 이 모듈은 단독 실행용 파이프라인 단계다.
#   python -m src.extract.step3_tag
# 경로는 src/config/paths.py 한 곳에서만 정의한다.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from src.config import paths
paths.ensure_dirs()
_KR = str(paths.DATA_DIR)
_SRC = str(paths.DATA_DIR)

# -*- coding: utf-8 -*-
"""STEP3~5: 속성 태깅 + 별칭 scope/type + 활성판정/로테이션 지표 → master.json"""
import json, re, collections, datetime, statistics

D = json.load(open(_KR + '/raw.json'))
G = json.load(open(_KR + '/groups.json'))
rid, recipes = G['rid'], G['recipes']

recipe_text = {n: v[0][0] for n, v in D['recipe_text'].items() if v}
allergy_txt = {n: v[0][0] for n, v in D['allergy_txt'].items() if v}
memo_txt    = {n: v[0][0] for n, v in D['memo_txt'].items() if v}
weights     = {n: v[0][0] for n, v in D['weights'].items() if v}
ea_cnt, occ_cnt = D['ea_cnt'], D['occ_cnt']
book = set(D['book_latest'])
recs = D['records']

LATEST = max(r['date'] for r in recs)
LATEST_D = datetime.date.fromisoformat(LATEST)
CUT = (LATEST_D - datetime.timedelta(days=365)).isoformat()

# ================= 3. 속성 태깅 =================
# --- 주재료: 자재사용내역 첫 성분 + 비율 상위 성분 ---
def main_ingredients(text, k=3):
    t = str(text)
    parts = re.split(r'(?<=[%\]\}])\s*,|,(?![^\[\{]*[\]\}])', t)
    out = []
    for p in parts:
        p = p.strip()
        if not p: continue
        m = re.match(r'^([^\(\[\{0-9]{2,12})', p)
        if not m: continue
        ing = m.group(1).strip(' ·.')
        pct = re.search(r'(\d+(?:\.\d+)?)\s*%', p)
        if ing and ing not in [o[0] for o in out]:
            out.append((ing, float(pct.group(1)) if pct else None))
        if len(out) >= k + 4: break
    return out[:k]

PROTEIN = {'돼지고기':'돈육','돈육':'돈육','돈후지':'돈육','돈사태':'돈육','돼지갈비':'돈육','돈채':'돈육',
           '족발':'돈육','목살':'돈육','삼겹':'돈육','돈갈비':'돈육','제육':'돈육','돈전지':'돈육',
           '돈민찌':'돈육','돼지갈비살':'돈육','돈등심':'돈육','등심':'돈육',
           '소고기':'우육','쇠고기':'우육','우육':'우육','소양지':'우육','우삼겹':'우육','차돌':'우육',
           '소불고기':'우육','소갈비':'우육','부채살':'우육','우민찌':'우육','소사태':'우육',
           '닭고기':'계육','닭정육':'계육','닭가슴살':'계육','닭다리':'계육','닭안심':'계육','훈제닭':'계육',
           '순살치킨':'계육','치킨':'계육','닭':'계육','닭봉':'계육','닭날개':'계육',
           '오리':'오리','훈제오리':'오리',
           '계란':'난류','전란':'난류','난백':'난류','난황':'난류','깐계란':'난류','메추리알':'난류',
           '새우':'새우','오징어':'연체','문어':'연체','낙지':'연체','쭈꾸미':'연체','대왕오징어':'연체',
           '두부':'두류','순두부':'두류','유부':'두류','콩나물':'두류','동부':'두류','녹두':'두류',
           '완두':'두류','병아리콩':'두류','렌즈콩':'두류',
           '어묵':'어육','볼어묵':'어육','연육':'어육','맛살':'어육',
           '동태':'어류','북어':'어류','황태':'어류','고등어':'어류','삼치':'어류','임연수':'어류',
           '가자미':'어류','대구':'어류','아귀':'어류','멸치':'어류','진미채':'어류','코다리':'어류',
           '햄':'가공육','소시지':'가공육','소세지':'가공육','베이컨':'가공육','미트볼':'가공육',
           '스팸':'가공육','캔햄':'가공육','후랑크':'가공육'}

# 조미료·미량 부재료 — 단백 기여로 보지 않는다 (§4-1은 주재료 얘기지 간장 속 대두 얘기가 아님)
SEASONING = ['새우젓','멸치육수','멸치액젓','액젓','굴소스','사골엑기스','치킨스톡','다시다',
             '간장','국간장','양조간장','된장','고추장','춘장','대두유','참기름','들기름',
             '짜장분말','카레분말','밥새우','건새우','두절건새우','소고기다시','쇠고기다시',
             '멸치다시','가쓰오','우스터','조개다시','굴']

PROTEIN_MIN_PCT = 10.0     # 이름에 안 나오는 재료는 이 비율 이상일 때만 주재료

def split_ing(text):
    """자재사용내역 → [(재료명, 비율 or None)]"""
    t = str(text)
    parts = re.split(r',(?![^\(\[\{]*[\)\]\}])', t)
    out = []
    for p in parts:
        p = p.strip(' .·')
        if not p: continue
        pct = re.search(r'(\d+(?:\.\d+)?)\s*%', p)
        name = re.split(r'[\(\[\{0-9]', p)[0].strip(' .·')
        if name: out.append((name, float(pct.group(1)) if pct else None))
    return out

def protein_of(text, menu):
    """주재료(단백) 추출.
    - 조미료 유래 성분은 제외
    - 메뉴명에 언급된 재료는 비율과 무관하게 인정
    - 그 외에는 비율 10% 이상만 인정
    """
    hits = []
    for name, pct in split_ing(text):
        if any(s in name for s in SEASONING): continue
        cat = None
        for k, v in PROTEIN.items():
            if k in name: cat = v; break
        if not cat: continue
        in_menu = any(k in menu for k, v in PROTEIN.items() if v == cat and k in name)
        if in_menu or (pct is not None and pct >= PROTEIN_MIN_PCT):
            if cat not in hits: hits.append(cat)
    return hits[:3]

# --- 조리방식 ---
COOK = [('국물', r'(국|탕|찌개)$'), ('튀김', r'(튀김|까스|카츠|강정|가라아게)'), ('구이', r'(구이|스테이크)'),
        ('볶음', r'(볶음|불고기|두루치기|잡채)'), ('조림', r'(조림|장조림|찜)'), ('무침', r'(무침|나물|겉절이)'),
        ('전', r'(전$|전구이|부침)'), ('샐러드', r'(샐러드|치즈드레싱)'), ('밥', r'(밥$|덮밥소스|주먹밥)'),
        ('김치', r'(김치$|깍두기$)'), ('면', r'(파스타|스파게티|국수|우동|떡볶이)')]
def cook_of(name):
    for lab, pat in COOK:
        if re.search(pat, name): return lab
    return '기타'

# --- 완제품 스코어 ---
BR = re.compile(r'^\s*([^,\[\{]{2,25})\s*[\[\{](.+?)[\]\}]\s*(\d+(?:\.\d+)?)?%?')
def norm_k(s): return re.sub(r'[^가-힣A-Za-z]', '', s)
def ready_score(name, aliases):
    s, why = 0, []
    txt = recipe_text.get(name, '')
    m = BR.match(str(txt))
    if m:
        s += 2; why.append(f'성분표블록({m.group(1).strip()})')
        if m.group(3) and float(m.group(3)) >= 50:
            s += 2; why.append(f'주재료비율{m.group(3)}%')
    ea = sum(ea_cnt.get(a, 0) for a in aliases)
    tot = sum(occ_cnt.get(a, 0) for a in aliases)
    if ea > 0:
        s += 2; why.append(f'EA관리{ea}/{tot}회')
    memo = memo_txt.get(name, '')
    if memo:
        nm, mm = norm_k(name), norm_k(memo)
        if sum(1 for i in range(len(nm) - 1) if nm[i:i+2] in mm) >= 2:
            s += 3; why.append(f'메모=동일품({memo[:28]})')
    return s, ' / '.join(why)

# --- 알레르기 번호 ---
def allergy_nums(name):
    for a in [name]:
        t = allergy_txt.get(a)
        if t is None: continue
        t = str(t).strip()
        if t in ('0', '0.0'): return []
        return sorted({int(x) for x in re.findall(r'\d+', t) if 1 <= int(x) <= 30})
    return None

PRIORITY = {1: '난류', 4: '견과류', 9: '새우', 18: '조개류'}

# ================= 4. 별칭 scope / type =================
# 같은 날 유아·성인 라인에 동시 등장 → 성인전용 변형
by_date_line = collections.defaultdict(set)
for r in recs:
    if r['line'] in ('유아', '성인'):
        by_date_line[(r['date'], r['line'])].add(r['name'])

alias_line = collections.defaultdict(collections.Counter)
for r in recs:
    if r['line'] in ('유아', '성인'):
        alias_line[r['name']][r['line']] += 1

same_day_pair = collections.Counter()
for r_id, v in recipes.items():
    al = v['aliases']
    if len(al) < 2: continue
    for (d, ln), names_ in by_date_line.items():
        if ln != '유아': continue
        k_ = names_ & set(al)
        a_ = by_date_line.get((d, '성인'), set()) & set(al)
        if k_ and a_ and k_ != a_:
            for x in a_ - k_: same_day_pair[x] += 1

MODP = re.compile(r'^(매콤한|매콤|얼큰|매운|빨간|마라)')
def alias_type(rep, a):
    if a == rep: return '기본'
    if MODP.match(a) and not MODP.match(rep): return '매운맛조정'
    ra = re.sub(r'.*?(국|탕|찌개|찜|볶음|조림|구이|무침|전|튀김)$', r'\1', a)
    rr = re.sub(r'.*?(국|탕|찌개|찜|볶음|조림|구이|무침|전|튀김)$', r'\1', rep)
    if ra != rr and ra and rr and len(ra) <= 3 and len(rr) <= 3: return '어미변형'
    return '주재료강조'

def alias_scope(a):
    c = alias_line[a]
    if same_day_pair.get(a, 0) > 0: return '성인전용'
    if c.get('유아', 0) and c.get('성인', 0): return '공용'
    if c.get('성인', 0) and not c.get('유아', 0): return '성인전용'
    if c.get('유아', 0) and not c.get('성인', 0): return '유아우선'
    return '미사용'

# ================= 5. 활성 판정 + 로테이션 =================
occ_by_recipe = collections.defaultdict(list)   # rid -> [(date, slot, line, name)]
for r in recs:
    x = rid.get(r['name'])
    if x: occ_by_recipe[x].append((r['date'], r['slot'], r['line'], r['name']))

alias_dates = collections.defaultdict(list)
for r in recs:
    alias_dates[r['name']].append(r['date'])

def gap_stats(dates):
    ds = sorted({datetime.date.fromisoformat(d) for d in dates})
    if len(ds) < 2: return None, None
    gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 3]
    if not gaps: return None, None
    return round(statistics.mean(gaps)), max(gaps)


# ================= 보조메뉴(&) 부모 귀속 =================
def is_side_name(n): return str(n).strip().startswith('&')

seq = collections.defaultdict(list)
for i, r in enumerate(recs): seq[(r['date'], r['line'])].append((i, r))

parent_link = {}          # 보조 record idx -> 부모 record idx
for k, v in seq.items():
    last_main = None
    for i, r in v:
        if is_side_name(r['name']):
            if last_main is not None: parent_link[i] = last_main
        else:
            last_main = i

# 레시피ID 단위 부모↔보조 관계
side_of_parent = collections.defaultdict(collections.Counter)   # 부모rid -> Counter(보조rid)
parent_of_side = collections.defaultdict(collections.Counter)   # 보조rid -> Counter(부모rid)
pair_last = {}                                                  # (부모rid,보조rid) -> 최종사용일
for si, pi in parent_link.items():
    srid = rid.get(recs[si]['name']); prid = rid.get(recs[pi]['name'])
    if not srid or not prid: continue
    side_of_parent[prid][srid] += 1
    parent_of_side[srid][prid] += 1
    key = (prid, srid)
    pair_last[key] = max(pair_last.get(key, ''), recs[si]['date'])

SIDE_RIDS = {rid[n] for n in rid if is_side_name(n)}

master = []
for r_id, v in recipes.items():
    rep, aliases = v['rep'], v['aliases']
    hist = occ_by_recipe.get(r_id, [])
    dates = sorted({h[0] for h in hist})
    last = dates[-1] if dates else None
    first = dates[0] if dates else None
    n_occ = len(dates)
    in_book = any(a in book for a in aliases)
    active = bool(last and last >= CUT)
    slots = collections.Counter(h[1] for h in hist if h[1])
    lines = collections.Counter(h[2] for h in hist if h[2])
    months = sorted({d[:7] for d in dates})
    avg_gap, max_gap = gap_stats(dates)
    rs, rwhy = ready_score(rep, aliases)
    alg = allergy_nums(rep)
    if alg is None:
        for a in aliases:
            alg = allergy_nums(a)
            if alg is not None: break
    alg = alg or []
    txt = recipe_text.get(rep, '')
    ings = main_ingredients(txt)
    prot = protein_of(txt, rep)

    if not in_book and not active:
        status = '폐지'
    elif active and in_book:
        status = '활성'
    elif active and not in_book:
        status = '활성(레시피북 누락)'
    else:
        status = '비활성(1년 미출현)'

    master.append({
        'recipe_id': r_id, 'rep': rep, 'status': status,
        'in_book': in_book, 'n_alias': len(aliases),
        'aliases': aliases,
        'slot_main': slots.most_common(1)[0][0] if slots else '',
        'slot_dist': ', '.join(f'{k}{v}' for k, v in slots.most_common()),
        'line_dist': ', '.join(f'{k}{v}' for k, v in lines.most_common()),
        'n_occ': n_occ, 'n_month': len(months),
        'first': first, 'last': last,
        'days_since': (LATEST_D - datetime.date.fromisoformat(last)).days if last else None,
        'avg_gap': avg_gap, 'max_gap': max_gap,
        'protein': ', '.join(prot),
        'ingredients': ', '.join(f'{a}{"("+str(b)+"%)" if b else ""}' for a, b in ings),
        'cook': cook_of(rep),
        'ready_score': rs, 'ready': rs >= 5, 'ready_why': rwhy,
        'allergy': '.'.join(str(x) for x in alg) if alg else '0',
        'allergy_priority': ', '.join(f'{n}({PRIORITY[n]})' for n in alg if n in PRIORITY),
        'weight_g': weights.get(rep, ''),
        'text': txt, 'memo': memo_txt.get(rep, ''),
        'months': months,
        'active_flag': 'O',        # 담당자가 시트에서 O/X 로 직접 조정 (기본 O)
        'is_side': r_id in SIDE_RIDS,
        'side_candidates': [(recipes[x]['rep'], c, pair_last.get((r_id, x), ''))
                            for x, c in side_of_parent[r_id].most_common()],
        'parent_candidates': [(recipes[x]['rep'], c, pair_last.get((x, r_id), ''))
                              for x, c in parent_of_side[r_id].most_common()],
    })

alias_rows = []
for m in master:
    for a in m['aliases']:
        ds = sorted(set(alias_dates.get(a, [])))
        alias_rows.append({
            'recipe_id': m['recipe_id'], 'alias': a, 'rep': m['rep'],
            'is_rep': a == m['rep'],
            'type': alias_type(m['rep'], a),
            'scope': alias_scope(a),
            'n_occ': len(ds), 'first': ds[0] if ds else '', 'last': ds[-1] if ds else '',
            'in_book': a in book,
        })

# ── 담당자 회신 반영 (2026-09) — 레시피북 미등재분은 '과일'만 유지, 나머지는 사용 안 함
KEEP_UNLISTED = {'과일'}
for m in master:
    if m['status'] == '활성(레시피북 누락)' and m['rep'] not in KEEP_UNLISTED:
        m['active_flag'] = 'X'
        m['flag_note'] = '2026-09 담당자 확인 — 레시피북 미등재, 사용 안 함'
n_off = sum(1 for m in master if m['active_flag'] == 'X')
print('사용여부 X 처리:', n_off, '종')

json.dump({'master': master, 'alias': alias_rows, 'latest': LATEST, 'cut': CUT},
          open(_KR + '/master.json', 'w'), ensure_ascii=False)

st = collections.Counter(m['status'] for m in master)
print('기준 최신일:', LATEST, ' / 1년 컷오프:', CUT)
print('레시피 상태:', st.most_common())
print('활성 계열:', sum(v for k, v in st.items() if k.startswith('활성')))
print('완제품 판정:', sum(1 for m in master if m['ready'] and m['status'].startswith('활성')))
print('별칭 행:', len(alias_rows), ' scope 분포:', collections.Counter(a['scope'] for a in alias_rows).most_common())
print('type 분포:', collections.Counter(a['type'] for a in alias_rows if not a['is_rep']).most_common())
print('보조(&) 레시피:', sum(1 for m in master if m['is_side']),
      ' / 보조를 거느린 부모 레시피:', sum(1 for m in master if m['side_candidates']))
print()
print('■ 성인전용 별칭 샘플')
for a in alias_rows:
    if a['scope'] == '성인전용' and not a['is_rep']:
        print(f"   {a['rep']}  →  {a['alias']}  [{a['type']}]")
