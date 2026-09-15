# -*- coding: utf-8 -*-
# 이 모듈은 단독 실행용 파이프라인 단계다.
#   python -m src.extract.recipe_book
# 경로는 src/config/paths.py 한 곳에서만 정의한다.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from src.config import paths
paths.ensure_dirs()
_KR = str(paths.DATA_DIR)
_SRC = str(paths.DATA_DIR)

# -*- coding: utf-8 -*-
"""STEP6: 레시피북 마스터 엑셀 생성"""
import json, collections, datetime, re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.formatting.rule import CellIsRule

M = json.load(open(_KR + '/master.json'))
G = json.load(open(_KR + '/groups.json'))
D = json.load(open(_KR + '/raw.json'))
master, alias_rows = M['master'], M['alias']
LATEST, CUT = M['latest'], M['cut']

FONT = 'Arial'
H_FILL = PatternFill('solid', fgColor='1F3864')
H_FONT = Font(name=FONT, size=10, bold=True, color='FFFFFF')
SUB_FILL = PatternFill('solid', fgColor='D9E2F3')
WARN_FILL = PatternFill('solid', fgColor='FCE4D6')
OK_FILL = PatternFill('solid', fgColor='E2EFDA')
GREY = Font(name=FONT, size=10, color='808080')
BASE = Font(name=FONT, size=10)
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

PRIORITY = {1: '난류', 4: '견과류', 9: '새우', 18: '조개류'}
rid_map = G['rid']

wb = openpyxl.Workbook()

def style_header(ws, ncol, row=1):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = H_FILL; cell.font = H_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    ws.auto_filter.ref = f'A{row}:{get_column_letter(ncol)}{ws.max_row}'

def widths(ws, spec):
    for col, w in spec.items():
        ws.column_dimensions[col].width = w

def put(ws, rows, header):
    ws.append(header)
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = BASE
            c.alignment = Alignment(vertical='top', wrap_text=False)

# ============ 0. README ============
ws = wb.active; ws.title = '00_README'
ws.column_dimensions['A'].width = 26
ws.column_dimensions['B'].width = 105

rd = [
    ('레시피북 마스터 테이블', ''),
    ('', ''),
    ('생성일', datetime.date.today().isoformat()),
    ('데이터 범위', '2025-08 ~ 2026-09 생산일지 14개월 (일자별 시트 + 레시피북/온라인_반찬)'),
    ('기준 최신일', LATEST),
    ('활성 판정 컷오프', f'{CUT} (최신일 기준 1년)'),
    ('', ''),
    ('■ 설계 원칙', ''),
    ('1. 정체성 = 레시피 ID',
     '중복 판정·로테이션 주기·주재료 충돌 검사는 전부 recipe_id 단위로 수행한다. 메뉴명은 보지 않는다.'),
    ('2. 표기 = 별칭 풀',
     '같은 recipe_id에 여러 표기명이 매달려 있다. 출력 단계에서 골라 쓴다. 같은 레시피를 다른 이름으로 내보내는 것은 '
     '내부 리소스(전처리·자재발주·조리라인)를 늘리지 않고 체감 다양성만 올리는 장치이므로, 제거 대상이 아니라 활용 자산이다.'),
    ('3. 활성 = 최신시점 기준 1년 내 출현',
     '레시피북에서 삭제된 것은 퇴출된 것으로 보고 복원하지 않는다. 다만 최근 1년 내 식단표에 등장했는데 '
     '최신 레시피북에 없다면 그것은 "이름만 바뀐 동일 레시피"이므로 별칭으로 흡수했다. (status = 활성(레시피북 누락))'),
    ('', ''),
    ('■ 담당자 직접 편집 (중요)', ''),
    ('사용여부 (O/X)', "01_레시피마스터의 노란 칸. X 로 바꾸면 그 메뉴는 초안 생성에서 제외된다. "
                       '클레임·이슈로 당분간 빼야 할 메뉴도 여기서 X 로 처리하면 된다. (별도 블랙리스트 불필요)'),
    ('신메뉴 추가', '01_레시피마스터 맨 아래에 행을 추가하고 대표명·자재사용내역·알레르기번호·기준중량 '
                    '네 칸만 채우면 다음 생성부터 후보에 들어간다. 사용여부는 O 로 둔다.'),
    ('담당자 비고', '왜 껐는지/언제 추가했는지 등을 자유롭게 적는 칸. 시스템은 읽지 않는다.'),
    ('분기 갱신', '새 생산일지를 받아 자동 컬럼(출현이력·자재내역·별칭 등)만 다시 계산하고, '
                  '사용여부와 담당자가 직접 추가한 행은 그대로 보존한다.'),
    ('', ''),
    ('■ 시트 구성', ''),
    ('01_레시피마스터', '레시피 ID 단위 마스터. 생성기가 후보 풀로 읽는 주 테이블.'),
    ('02_별칭매핑', '표기명 → 레시피 ID. scope/type 태그 포함. 출력 단계에서 이름을 고를 때 참조.'),
    ('03_출현이력', '레시피 × 월별 출현 횟수. 로테이션 주기 위반 검사용.'),
    ('04_편성원장', '일자별 편성 전수 기록 (날짜·라인·자리·메뉴·레시피ID). 모든 집계의 원천.'),
    ('05_검증리포트', '알레르기 정합성·자재내역 중복·미매핑 등 담당자 확인 항목.'),
    ('06_담당자확인', '자동 판정을 보류한 항목. 문서 §14에 해당.'),
    ('07_보조매핑', "'&' 보조메뉴 ↔ 부모메뉴 동반 이력. 부모 배치 후 보조를 고를 때 참조."),
    ('', ''),
    ('■ status 값 정의', ''),
    ('활성', '최신 레시피북에 등재 + 최근 1년 내 출현. → 생성기 후보 풀'),
    ('활성(레시피북 누락)', '최근 1년 내 출현했으나 최신 레시피북에 없음. 개명 흡수 대상 또는 등재 누락. → 후보 풀 포함하되 확인 필요'),
    ('비활성(1년 미출현)', '레시피북에는 있으나 최근 1년간 한 번도 안 나옴. → 퇴출 간주, 후보 제외'),
    ('폐지', '레시피북에도 없고 최근 1년 출현도 없음. → 이력 보존용'),
    ('', ''),
    ('■ 보조메뉴(&) 처리 원칙', ''),
    ('정의', "메뉴명이 '&'로 시작하는 항목은 독립 메뉴가 아니라 직전 메뉴에 딸린 보조(소스·드레싱·양념장·곁들임)다. "
              '식단표에는 한 줄로 표기되지만 하루 구조상 칸을 차지하지 않는다. '
              '예: 한입새우튀김 + & 레몬크림소스 → 표기는 2줄, 구조는 메인 1칸.'),
    ('자리(slot)', '보조에는 자리를 부여하지 않는다. 하루 구조는 밥/메인/서브1/서브2/김치/국 6칸을 그대로 유지한다.'),
    ('로테이션', '보조는 메인·서브·국의 로테이션 주기 계산과 자리 배정 통계에서 제외한다. '
                 '보조여부 컬럼이 "보조"인 행은 생성기의 자리 후보 풀에 넣지 않는다.'),
    ('알레르기', '보조는 부모와 한 몸으로 먹는 것이므로 부모 메뉴의 일부로 본다. '
                 '별도 메뉴로 알레르기 중복을 이중 계산하지 않고, 부담이 크면 다른 반찬으로 보완한다.'),
    ('부모-보조 매핑', '고정 매핑이 아니다. 문서 §11대로 그날 메뉴와 겹치지 않게 바꿔 쓰므로, '
                       '07_보조매핑의 후보 목록에서 중복 회피 규칙으로 고른다. '
                       '예: 목화솜탕수육 → 탕수소스(8) / 스위트칠리소스(3) / 레몬크림소스(3) 교대 사용.'),
    ('검증', '14개월 보조 133건이 모두 부모에 귀속됐고(고아 0건), 보조 제외 후 467일이 정확히 6칸 구성으로 복원됨.'),
    ('', ''),
    ('■ 완제품(ready) 판정 근거', ''),
    ('신호 A (2~4점)', '자재사용내역이 "제품명[성분,성분...]" 형태 = 제조사 성분표 복붙. 주재료 비율 50% 이상이면 가산'),
    ('신호 B (2점)', '일자별 시트에서 중량(g)이 아닌 수량(EA)으로 관리됨'),
    ('신호 C (3점)', '메모의 브랜드 제품명이 메뉴명과 일치 (예: 치킨너겟 → 치킨너겟(하림))'),
    ('판정', '합계 5점 이상 = 완제품. 4점 이하는 담당자 확인 권장'),
    ('검증', '이 판정으로 "완제품이 메인 자리에 온 날"을 14개월 집계하면 월 0~3일 — 규칙 §4-3(월 2회, 최대 3회)과 일치'),
    ('', ''),
    ('■ 별칭 scope 정의 (중요)', ''),
    ('공용', '유아·성인 라인 양쪽에서 사용. 어느 쪽에나 배치 가능'),
    ('성인전용', '같은 날 유아식과 성인식에 서로 다른 이름이 동시 등장 → 성인식 변형(§10-1). 유아식 후보에 넣으면 안 됨'),
    ('유아우선', '유아 라인에서만 관측'),
    ('미사용', '레시피북에는 있으나 최근 14개월 편성 이력 없음'),
    ('', ''),
    ('■ 별칭 type 정의', ''),
    ('매운맛조정', '매콤/얼큰/매운/빨간/마라 접두 — 대부분 성인식 변형'),
    ('어미변형', '찜↔볶음, 무침↔조림, 국↔탕 — 같은 날 조리방식 중복을 해소하려고 이름만 바꾼 것(§8)'),
    ('주재료강조', '들어간 재료 중 어느 것을 이름에 세울지 바꾼 것 (맑은감자국↔황태감자국)'),
]
for k, v in rd:
    ws.append([k, v])
ws['A1'].font = Font(name=FONT, size=16, bold=True, color='1F3864')
for r in ws.iter_rows(min_row=2):
    for c in r:
        if c.font is None or c.row == 1: continue
        c.font = BASE
        c.alignment = Alignment(vertical='top', wrap_text=True)
for r in ws.iter_rows(min_col=1, max_col=1):
    v = str(r[0].value or '')
    if v.startswith('■'):
        r[0].font = Font(name=FONT, size=11, bold=True, color='1F3864')

# ============ 1. 레시피마스터 ============
ws = wb.create_sheet('01_레시피마스터')
HDR = ['레시피ID', '대표명', '사용여부\n(O/X)', '담당자 비고',
       'status', '보조여부', '보조후보', '부모후보',
       '최신레시피북\n등재', '별칭수', '별칭목록',
       '주자리', '자리분포', '라인분포', '주재료(단백)', '핵심재료', '조리방식',
       '완제품', '완제품점수', '완제품근거', '알레르기번호', '최우선알레르기',
       '출현횟수', '출현월수', '최초출현', '최종출현', '경과일',
       '평균간격(일)', '최대간격(일)', '기준중량(g)', '자재사용내역', '메모']
order = {'활성': 0, '활성(레시피북 누락)': 1, '비활성(1년 미출현)': 2, '폐지': 3}
rows = []
for m in sorted(master, key=lambda x: (order.get(x['status'], 9), -x['n_occ'], x['rep'])):
    rows.append([
        m['recipe_id'], m['rep'],
        m.get('active_flag', 'O'), m.get('flag_note', ''),
        m['status'],
        '보조' if m['is_side'] else '',
        ' | '.join(f'{n}({c})' for n, c, _ in m['side_candidates'][:6]),
        ' | '.join(f'{n}({c})' for n, c, _ in m['parent_candidates'][:6]),
        'O' if m['in_book'] else '',
        m['n_alias'], ' | '.join(a for a in m['aliases'] if a != m['rep']),
        m['slot_main'], m['slot_dist'], m['line_dist'],
        m['protein'], m['ingredients'], m['cook'],
        'O' if m['ready'] else '', m['ready_score'], m['ready_why'],
        m['allergy'], m['allergy_priority'],
        m['n_occ'], m['n_month'], m['first'] or '', m['last'] or '',
        m['days_since'] if m['days_since'] is not None else '',
        m['avg_gap'] or '', m['max_gap'] or '',
        m['weight_g'] or '', str(m['text'])[:500], str(m['memo'])[:120],
    ])
put(ws, rows, HDR)
style_header(ws, len(HDR))
widths(ws, {'A': 9, 'B': 22, 'C': 9, 'D': 34, 'E': 18, 'F': 8, 'G': 40, 'H': 34,
            'I': 9, 'J': 7, 'K': 34, 'L': 8, 'M': 20, 'N': 16, 'O': 14, 'P': 30,
            'Q': 9, 'R': 8, 'S': 9, 'T': 40, 'U': 16, 'V': 18, 'W': 8, 'X': 8,
            'Y': 11, 'Z': 11, 'AA': 7, 'AB': 10, 'AC': 10, 'AD': 10, 'AE': 60, 'AF': 30})
ws.row_dimensions[1].height = 32
last = ws.max_row
ws.conditional_formatting.add(f'E2:E{last}', CellIsRule(operator='equal', formula=['"활성"'], fill=OK_FILL))
ws.conditional_formatting.add(f'C2:C{last}', CellIsRule(operator='equal', formula=['"X"'],
                              fill=PatternFill('solid', fgColor='FFD9D9D9')))
ws.conditional_formatting.add(f'F2:F{last}', CellIsRule(operator='equal', formula=['"보조"'], fill=SUB_FILL))
# 사용여부·비고는 담당자 입력란
for r in range(2, last + 1):
    ws.cell(row=r, column=3).fill = PatternFill('solid', fgColor='FFFFFF99')
    ws.cell(row=r, column=4).fill = PatternFill('solid', fgColor='FFFFFF99')
from openpyxl.worksheet.datavalidation import DataValidation
dv = DataValidation(type='list', formula1='"O,X"', allow_blank=False)
ws.add_data_validation(dv); dv.add(f'C2:C{last}')

# ============ 2. 별칭매핑 ============
ws = wb.create_sheet('02_별칭매핑')
HDR2 = ['레시피ID', '표기명', '대표명여부', '대표명', 'type', 'scope',
        '레시피북등재', '출현횟수', '최초사용', '최종사용', '표기명재사용가능']
amap = {m['recipe_id']: m for m in master}
rows = []
for a in sorted(alias_rows, key=lambda x: (x['recipe_id'], not x['is_rep'], x['alias'])):
    m = amap[a['recipe_id']]
    reuse = ''
    if not a['is_rep'] and a['last']:
        reuse = 'O'
    rows.append([a['recipe_id'], a['alias'], 'O' if a['is_rep'] else '', a['rep'],
                 a['type'], a['scope'], 'O' if a['in_book'] else '',
                 a['n_occ'], a['first'], a['last'], reuse])
put(ws, rows, HDR2)
style_header(ws, len(HDR2))
widths(ws, {'A': 9, 'B': 26, 'C': 10, 'D': 22, 'E': 13, 'F': 11, 'G': 11,
            'H': 9, 'I': 11, 'J': 11, 'K': 13})
ws.row_dimensions[1].height = 30
last = ws.max_row
ws.conditional_formatting.add(f'F2:F{last}',
    CellIsRule(operator='equal', formula=['"성인전용"'], fill=WARN_FILL))

# ============ 3. 출현이력 ============
ws = wb.create_sheet('03_출현이력')
months = sorted({mm for m in master for mm in m['months']})
HDR3 = ['레시피ID', '대표명', 'status', '주자리'] + months + ['합계']
rows = []
for m in sorted(master, key=lambda x: (order.get(x['status'], 9), x['rep'])):
    if not m['months']: continue
    cnt = collections.Counter(m['months'])
    # 월별 실제 편성일수
    row = [m['recipe_id'], m['rep'], m['status'], m['slot_main']]
    per = {mo: 0 for mo in months}
    rows.append((row, per, m))
# 월별 카운트 재산출
by_rid_month = collections.Counter()
rid_map = G['rid']
for r in D['records']:
    x = rid_map.get(r['name'])
    if x: by_rid_month[(x, r['date'][:7])] += 1
out = []
for row, per, m in rows:
    vals = [by_rid_month.get((m['recipe_id'], mo), 0) for mo in months]
    out.append(row + vals + [None])   # 합계는 시트 내 SUM 수식으로 기입
put(ws, out, HDR3)
# 합계 컬럼을 SUM 수식으로 (원본 값 변경 시 재계산되도록)
c1 = get_column_letter(5)
c2 = get_column_letter(4 + len(months))
tot = 5 + len(months)
for r in range(2, ws.max_row + 1):
    ws.cell(row=r, column=tot).value = f'=SUM({c1}{r}:{c2}{r})'
style_header(ws, len(HDR3))
widths(ws, {'A': 9, 'B': 22, 'C': 18, 'D': 8})
for i in range(len(months)):
    ws.column_dimensions[get_column_letter(5 + i)].width = 8
ws.column_dimensions[get_column_letter(5 + len(months))].width = 8
ws.row_dimensions[1].height = 30
last = ws.max_row
rng = f'{get_column_letter(5)}2:{get_column_letter(4+len(months))}{last}'
ws.conditional_formatting.add(rng, CellIsRule(operator='greaterThan', formula=['0'], fill=SUB_FILL))

# ============ 4. 편성원장 ============
ws = wb.create_sheet('04_편성원장')
HDR4 = ['날짜', '월', '라인', '자리', '표기명', '레시피ID', '대표명',
        '보조여부', '부모메뉴', '중량(g)', '제공인원']
# 원본 순서 기준으로 부모 귀속
_seq = collections.defaultdict(list)
for _i, _r in enumerate(D['records']): _seq[(_r['date'], _r['line'])].append((_i, _r))
_parent = {}
for _k, _v in _seq.items():
    _lm = None
    for _i, _r in _v:
        if str(_r['name']).strip().startswith('&'):
            if _lm is not None: _parent[_i] = D['records'][_lm]['name']
        else: _lm = _i
rows = []
for _i, r in sorted(enumerate(D['records']),
                    key=lambda t: (t[1]['date'], str(t[1]['line']), str(t[1]['slot']))):
    x = rid_map.get(r['name'], '')
    side = str(r['name']).strip().startswith('&')
    rows.append([r['date'], r['date'][:7], r['line'] or '', r['slot'] or '',
                 r['name'], x, amap[x]['rep'] if x in amap else '',
                 '보조' if side else '', _parent.get(_i, ''),
                 r['g'] or '', r['ppl'] or ''])
put(ws, rows, HDR4)
style_header(ws, len(HDR4))
widths(ws, {'A': 12, 'B': 9, 'C': 12, 'D': 8, 'E': 26, 'F': 9, 'G': 22,
            'H': 9, 'I': 22, 'J': 9, 'K': 10})

# ============ 5. 검증리포트 ============
ws = wb.create_sheet('05_검증리포트')
HDR5 = ['유형', '심각도', '대상', '내용', '조치']
vrows = []

# (a) 자재내역 동일하나 이름 무관 → 입력오류/개명 보류
for a, b, why in G['rejected']:
    sev = '높음' if why.startswith('입력오류') else '보통'
    vrows.append(['자재내역 중복', sev, f'{a} ↔ {b}', why,
                  '레시피 확인 후 통합하거나 자재내역 수정'])

# (b) 알레르기 정합성 — 최우선 4개(1/4/9/18)만 검사. 문서 §7-1
#     간접 함유(시판 소스·가공품 내부 성분)는 정상이므로 캐리어가 있으면 통과시킨다.
DIRECT = {1: ['계란','난황','난백','전란','메추리알'],
          4: ['호두','아몬드','땅콩','캐슈','케슈','잣','피칸','견과'],
          9: ['새우','대하','칵테일새우'],
          18: ['조개','굴','바지락','홍합','전복','키조개','가리비']}
CARRIER = {1: ['마요네즈','타르타르','어묵','만두','까스','카츠','튀김','빵','면','소스','드레싱','크림','케이크','전분가공품','후리가케'],
           4: ['페스토','드레싱','소스','시즈닝','카레','스프'],
           9: ['새우젓','어묵','육수','액젓','젓갈','김치','소스','스프','다시','해물'],
           18: ['굴소스','액젓','육수','젓갈','김치','어묵','짬뽕','해물','소스','다시','스톡']}
for m in master:
    if not m['status'].startswith('활성'): continue
    txt = str(m['text'])
    if not txt.strip(): continue
    nums = [int(x) for x in m['allergy'].split('.') if x.isdigit()] if m['allergy'] not in ('0','') else []
    for n in (1, 4, 9, 18):
        has_direct = any(k in txt for k in DIRECT[n])
        has_carrier = any(k in txt for k in CARRIER[n])
        if n in nums and not has_direct and not has_carrier:
            vrows.append(['최우선알레르기 정합성', '높음', f"{m['recipe_id']} {m['rep']}",
                          f'{n}번({PRIORITY[n]}) 표기돼 있으나 자재사용내역에 해당 재료도, 이를 함유할 가공품도 없음',
                          '레시피 변경 후 번호 미수정 여부 확인 (문서 §7-2 사례)'])
        if n not in nums and has_direct:
            vrows.append(['최우선알레르기 누락', '높음', f"{m['recipe_id']} {m['rep']}",
                          f'자재사용내역에 {"/".join([k for k in DIRECT[n] if k in txt][:2])}가 있으나 {n}번({PRIORITY[n]}) 미표기',
                          '알레르기 번호 추가 필요 여부 확인'])

# (b-2) 같은 날 최우선 알레르기 중복 — 과거 실적 기준 (규칙 §7-1 위반 이력)
day_alg = collections.defaultdict(lambda: collections.defaultdict(list))
alg_of = {m['recipe_id']: [int(x) for x in m['allergy'].split('.') if x.isdigit()]
          for m in master if m['allergy'] not in ('0','')}
for r in D['records']:
    if r['line'] not in ('유아','성인') or not r['slot']: continue
    if str(r['name']).strip().startswith('&'): continue   # 보조는 부모에 귀속, 이중계산 안 함
    x = rid_map.get(r['name'])
    for n in alg_of.get(x, []):
        if n in (1,4,9,18):
            day_alg[(r['date'], r['line'])][n].append(r['name'])
for (d, ln), dd in sorted(day_alg.items()):
    if d < CUT: continue
    for n, names_ in dd.items():
        u = sorted(set(names_))
        if len(u) >= 3:
            vrows.append(['동일일자 알레르기 중복', '낮음', f'{d} {ln}',
                          f'{n}번({PRIORITY[n]}) 보유 메뉴 {len(u)}개 동시 편성: {", ".join(u)}',
                          '참고 — 담당자 실제 편성 이력. 생성기 허용 한계 산정에 활용'])

# (c) 레시피북 누락
for m in master:
    if m['status'] == '활성(레시피북 누락)':
        vrows.append(['레시피북 누락', '보통', f"{m['recipe_id']} {m['rep']}",
                      f"최근 1년 내 {m['n_occ']}회 편성됐으나 최신 레시피북 미등재 (최종 {m['last']})",
                      '개명 흡수 대상인지 확인 후 레시피북 등재'])

# (d) 자재내역 없음
for m in master:
    if m['status'].startswith('활성') and not str(m['text']).strip():
        vrows.append(['자재내역 없음', '높음', f"{m['recipe_id']} {m['rep']}",
                      '활성 메뉴이나 자재사용내역이 비어 있음', '레시피 입력 필요'])

# (e) 원본 날짜 입력오류 / 중복 시트
for e in D.get('date_errors', []):
    if e['cell_date'] != e['fixed_to']:
        vrows.append(['원본 날짜 오류', '높음', f"{e['file']} 시트 \"{e['sheet']}\"",
                      f"A3 날짜가 {e['cell_date']}로 입력돼 있음 (연도 오타 추정) → {e['fixed_to']}로 교정 처리",
                      '원본 파일 A3 셀 수정 권장 — HowToUse §6·7에 따라 나머지 값이 이 셀을 참조함'])
    else:
        vrows.append(['타월 시트 혼재', '낮음', f"{e['file']} 시트 \"{e['sheet']}\"",
                      f"파일의 월과 다른 날짜({e['cell_date']}) 시트가 포함돼 있음",
                      '참고 — 다음달분 선작업으로 보임'])
for e in D.get('slot_on_side', []):
    vrows.append(['보조 자리 배정', '보통', f"{e['date']} {e['line']}",
                  f"보조메뉴 '{e['name']}'이 원본에서 '{e['slot']}' 자리를 차지하고 있었음 "
                  f"(그날 김치 칸이 밀려남)",
                  '보조는 자리를 갖지 않는 원칙에 따라 자리를 비움. 원본 구분 열 확인 권장'])

_dups = D.get('dup_records', [])
if _dups:
    _dd = collections.Counter(x['date'] for x in _dups)
    for d, c in _dd.items():
        vrows.append(['중복 시트', '보통', d,
                      f'같은 날짜·라인·자리·메뉴 레코드가 {c}건 중복 (시트 복제본 추정)',
                      '집계에서는 자동 제거함. 원본 정리 권장'])

sev_order = {'높음': 0, '보통': 1, '낮음': 2}
vrows.sort(key=lambda r: (sev_order.get(r[1], 9), r[0], r[2]))
put(ws, vrows, HDR5)
style_header(ws, len(HDR5))
widths(ws, {'A': 18, 'B': 9, 'C': 34, 'D': 72, 'E': 34})
last = ws.max_row
ws.conditional_formatting.add(f'B2:B{last}',
    CellIsRule(operator='equal', formula=['"높음"'], fill=WARN_FILL))


# ============ 7. 보조매핑 ============
ws = wb.create_sheet('07_보조매핑')
HDR7 = ['부모 레시피ID', '부모 대표명', '부모 자리', '보조 레시피ID', '보조 표기명',
        '동반 횟수', '최종 동반일', '부모의 보조 후보수', '비고']
srows = []
for m in sorted(master, key=lambda x: (-len(x['side_candidates']), x['rep'])):
    if not m['side_candidates']: continue
    n_cand = len(m['side_candidates'])
    for nm, c, lastd in m['side_candidates']:
        sid = next((z['recipe_id'] for z in master if z['rep'] == nm), '')
        note = '고정 조합 (후보 1개)' if n_cand == 1 else f'교대 사용 (후보 {n_cand}개 중 하나)'
        srows.append([m['recipe_id'], m['rep'], m['slot_main'], sid, nm, c, lastd, n_cand, note])
put(ws, srows, HDR7)
style_header(ws, len(HDR7))
widths(ws, {'A': 12, 'B': 22, 'C': 9, 'D': 12, 'E': 24, 'F': 10, 'G': 12, 'H': 15, 'I': 28})
ws.row_dimensions[1].height = 30
last = ws.max_row
ws.conditional_formatting.add(f'H2:H{last}',
    CellIsRule(operator='greaterThan', formula=['1'], fill=SUB_FILL))

# ============ 6. 담당자확인 ============
ws = wb.create_sheet('06_담당자확인')
HDR6 = ['구분', '항목', '현재 자동판정', '확인 요청 내용', '담당자 회신']
q = [
    ['활성 경계', '비활성(1년 미출현) 166건',
     '최종출현 1년 초과 → 후보 제외',
     '경계선(11~13개월)에 걸린 메뉴가 정말 폐지인지, 정상 로테이션의 긴 꼬리인지 확인 필요', ''],
    ['레시피북 누락', '활성(레시피북 누락) 60건',
     '별칭으로 흡수 또는 단독 활성 처리',
     '각 건이 (1)개명 (2)등재 누락 (3)실제 폐지 중 무엇인지 판정 필요. 05_검증리포트 참조', ''],
    ['완제품 판정', '4점대 경계 메뉴',
     '5점 이상만 완제품 처리',
     '녹두전·채소계란전처럼 완제품이지만 전(煎) 형태라 티가 덜 나는 건이 경계에 있음', ''],
    ['블랙리스트', '미구현',
     '없음',
     '클레임·뉴스이슈로 일시 제외할 메뉴 목록 입력 필요 (문서 §9-1). 이 시트에 직접 기입 요청', ''],
    ['보조메뉴 후보', '부모 27종 / 보조 37종',
     '과거 동반 이력 기반 후보 목록',
     '보조가 1종뿐인 부모(고정 조합)와 여러 종이 교대하는 부모의 구분이 맞는지 확인 필요. 07_보조매핑 참조', ''],
    ['제철·신메뉴', '자동화 제외',
     '없음',
     '그달 제철 재료 및 신메뉴는 초안 생성 후 담당자가 끼워 넣는 슬롯으로 남김 (문서 §11)', ''],
    ['납품처별 요구', '자동화 제외',
     '없음',
     '매운맛 정도·메뉴 교체 요구가 납품처마다 달라 일률 규칙화 불가 (문서 §10)', ''],
    ['조리실 사정', '자동화 제외',
     '없음',
     '전처리 부담·휴가 계획에 따른 조정은 패턴화되지 않아 후처리 영역 (문서 §6)', ''],
]
put(ws, q, HDR6)
style_header(ws, len(HDR6))
widths(ws, {'A': 16, 'B': 26, 'C': 26, 'D': 76, 'E': 30})
for r in range(2, ws.max_row + 1):
    ws.cell(row=r, column=5).fill = PatternFill('solid', fgColor='FFFF00')
    for c in range(1, 6):
        ws.cell(row=r, column=c).alignment = Alignment(vertical='top', wrap_text=True)

# 시트 순서 정리
wb._sheets = [wb[n] for n in ['00_README','01_레시피마스터','02_별칭매핑','03_출현이력',
                              '04_편성원장','05_검증리포트','06_담당자확인','07_보조매핑']]
wb.save(_KR + '/키즈락_레시피북_마스터.xlsx')
print('저장 완료')
print('레시피마스터 행:', len(master))
print('별칭매핑 행:', len(alias_rows))
print('편성원장 행:', len(D['records']))
print('검증리포트 행:', len(vrows))
print('검증 유형별:', collections.Counter(v[0] for v in vrows).most_common())
