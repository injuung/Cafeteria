# -*- coding: utf-8 -*-
# 이 모듈은 단독 실행용 파이프라인 단계다.
#   python -m src.extract.step2_group
# 경로는 src/config/paths.py 한 곳에서만 정의한다.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from src.config import paths
paths.ensure_dirs()
_KR = str(paths.DATA_DIR)
_SRC = str(paths.DATA_DIR)

# -*- coding: utf-8 -*-
"""STEP2: 자재사용내역 기준 레시피 ID 부여 + 별칭 그룹핑 (이름 친화도 가드 포함)"""
import json, re, collections, itertools

D = json.load(open(_KR + '/raw.json'))
recipe_text = D['recipe_text']

def norm_text(t):
    t = str(t)
    t = re.sub(r'\([^)]*\)', '', t)
    t = re.sub(r'\[[^\]]*\]', '', t)
    t = re.sub(r'\{[^}]*\}', '', t)
    t = re.sub(r'\d+(\.\d+)?%?', '', t)
    t = re.sub(r'[\s·,\.\-_/&]+', ',', t)
    return [x for x in t.split(',') if x]

STOP = {'정제수','소금','마늘','대파','파','설탕','물엿','후추','참기름','참깨','간장','국간장',
        '맛술','대두유','식용유','고춧가루','고추가루','깨','생강','생강가루','월계수잎','전분',
        '녹말가루','치킨스톡','멸치육수농축액','올리고당','미림','통깨','들기름','조미료','등','외'}

def sig(t):
    return [x for x in norm_text(t) if x not in STOP]

def jac(a, b):
    A, B = set(a), set(b)
    return len(A & B) / len(A | B) if A and B else 0.0

# ---------- 이름 친화도 가드 ----------
MOD = r'^(매콤한|매콤|얼큰|매운|빨간|순한|맑은|저염|양념|간장|고추장|마라|로제|순살|미니|왕|한입|꼬마|프리미엄)'
SUF = r'(국|탕|찌개|찜|볶음|조림|구이|무침|나물|샐러드|전|튀김)$'

def core(n):
    s = n
    for _ in range(3):
        s2 = re.sub(MOD, '', s)
        if s2 == s: break
        s = s2
    return re.sub(SUF, '', s)

def ngrams(s, k=2):
    s = re.sub(r'[^가-힣A-Za-z]', '', s)
    return {s[i:i+k] for i in range(len(s)-k+1)}

def name_affinity(a, b):
    """동일 레시피로 볼 만한 이름 관계인가"""
    ca, cb = core(a), core(b)
    if ca and cb and (ca == cb or ca in cb or cb in ca): return True
    if ngrams(a) & ngrams(b): return True          # 2-gram 공유
    return False

def ing_consistent(name, text):
    """메뉴명의 2-gram 중 하나라도 자재내역에 등장하는가"""
    t = re.sub(r'[^가-힣A-Za-z]', '', str(text))
    g = ngrams(name)
    return any(x in t for x in g)

def classify_reject(a, b, text):
    ca, cb = ing_consistent(a, text), ing_consistent(b, text)
    if ca and cb:
        return '개명 가능성 — 이름 연관 없으나 재료는 양쪽 다 부합 (담당자 확인)'
    return '입력오류 의심 — 메뉴명 재료가 자재내역에 없음 (복사·붙여넣기 추정)'

main_text = {n: v[0][0] for n, v in recipe_text.items() if v}
PLACEHOLDER = re.compile(r'자재입력|대기중|^0$')
names = sorted(n for n, t in main_text.items() if not PLACEHOLDER.search(t) and len(t) > 10)
sigs = {n: sig(main_text[n]) for n in names}

parent = {n: n for n in names}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: parent[rb] = ra

merged, rejected = [], []

# ── 담당자 확정 수동 병합 (2026-09 더바른푸드 박도영 대리 회신)
MANUAL_MERGE = [
    ('햄버거스테이크', '갈릭햄버거스테이크'),   # 갈릭스테이크소스를 뿌려 제공하는 방식으로 변경
    ('순살아귀탕', '맑은아귀국'),             # 명칭 변경
]
for a, b in MANUAL_MERGE:
    if a in parent and b in parent:
        union(a, b); merged.append((a, b, 1.0, '담당자 확정 개명'))

# 1) 완전일치
exact = collections.defaultdict(list)
for n in names:
    exact[','.join(norm_text(main_text[n]))].append(n)
for key, grp in exact.items():
    if len(key) < 12: continue
    for a, b in itertools.combinations(grp, 2):
        if name_affinity(a, b):
            union(a, b); merged.append((a, b, 1.0, '완전일치'))
        else:
            rejected.append((a, b, classify_reject(a, b, main_text[a])))

# 1.5) 조미료 제외 후 핵심재료 집합이 완전히 같은 경우 (얼큰~ / 매콤~ 접두 변형 포착)
coreset = collections.defaultdict(list)
for n in names:
    if len(sigs[n]) >= 2:
        coreset[','.join(sorted(set(sigs[n])))].append(n)
for key, grp in coreset.items():
    for a, b in itertools.combinations(grp, 2):
        if find(a) == find(b): continue
        if name_affinity(a, b):
            union(a, b); merged.append((a, b, 1.0, '핵심재료 동일'))

# 2) 유사도 매칭
bucket = collections.defaultdict(list)
for n in names:
    if sigs[n]: bucket[sigs[n][0]].append(n)
for k, grp in bucket.items():
    for a, b in itertools.combinations(grp, 2):
        if find(a) == find(b): continue
        sa, sb = sigs[a], sigs[b]
        if len(sa) < 4 or len(sb) < 4: continue
        j = jac(sa, sb)
        if j >= 0.90 and name_affinity(a, b):
            union(a, b); merged.append((a, b, round(j, 3), '유사도'))

groups = collections.defaultdict(list)
for n in names: groups[find(n)].append(n)
# 자재내역 없는 메뉴도 단독 ID 부여
for n in set(D['occ_cnt']) | set(D['book_latest']):
    if n not in parent: groups[n].append(n)

occ, book = D['occ_cnt'], set(D['book_latest'])
def pick_rep(grp):
    return sorted(grp, key=lambda n: (0 if n in book else 1, -occ.get(n, 0), len(n)))[0]

recipes, rid = {}, {}
for i, (root, grp) in enumerate(sorted(groups.items(), key=lambda kv: pick_rep(kv[1])), 1):
    r = f'R{i:04d}'
    for n in grp: rid[n] = r
    recipes[r] = {'rep': pick_rep(grp), 'aliases': sorted(grp),
                  'text': main_text.get(pick_rep(grp), '')}

multi = {r: v for r, v in recipes.items() if len(v['aliases']) > 1}
print('총 레시피 ID:', len(recipes))
print('별칭 2개 이상:', len(multi), ' / 병합쌍:', len(merged), ' / 반려(입력오류 의심):', len(rejected))
print()
for r, v in sorted(multi.items(), key=lambda kv: -len(kv[1]['aliases']))[:22]:
    print(f"  {r} [{v['rep']}] :: {' | '.join(a for a in v['aliases'] if a != v['rep'])}")
print()
print('■ 반려된 쌍 (검증리포트行)')
for a, b, why in rejected[:12]: print(f'  {a}  ↔  {b}')

json.dump({'rid': rid, 'recipes': recipes, 'merged': merged, 'rejected': rejected},
          open(_KR + '/groups.json', 'w'), ensure_ascii=False)
