# -*- coding: utf-8 -*-
# 이 모듈은 단독 실행용 파이프라인 단계다.
#   python -m src.extract.production_sheet
# 경로는 src/config/paths.py 한 곳에서만 정의한다.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from src.config import paths
paths.ensure_dirs()
_KR = str(paths.DATA_DIR)
_SRC = str(paths.DATA_DIR)

# -*- coding: utf-8 -*-
"""
8단계(개정) — 기존 '생산일지' 파일과 동일한 구조·서식으로 출력
  시트 구성: 글로벌리더스&석식식단표 / 유아식단표 / 레시피북 / 일자별 시트 / HowToUse
  알레르기·자재사용내역은 원본과 동일하게 레시피북을 INDEX+MATCH로 참조
"""
import sys, datetime, collections, re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter as L
from src.domain.repository import Repository
from src.planner.labels import display_name, attach_sides
from src.planner.placer import generate_month
from src.planner.adult import build_swap_map, to_adult, divergence
from src.export.adapters import flatten, month_business_days

FONT = '맑은 고딕'
GREEN = 'FF92D050'      # 식단표 제목 배경
ORANGE = 'FFFFC000'     # 날짜 행 배경
BLUE = 'FFC6DAF1'       # 일자별 시트 구분(라인) 배경
YELLOW = 'FFFFFF99'     # 담당자 입력란

LEGEND = (
    '원산지 안내\n'
    '쌀(국산),현미(국산. 친환경), 찰흑미(국산. 친환경), 찰보리(국산. 친환경), \n'
    '소고기(호주산), 돈육(국산), 목살(폭찹스테이크:미국산), 닭고기(국산. 무항생제), '
    '닭정육(닭다리살:국산, 브라질산), 훈제오리(무항생제.국산)\n'
    '배추김치(국산 종가집.하선정), 깍두기(무,고추가루:국산), \n'
    '오징어(국산,페루산,미국산, 칠레산), 낙지(베트남산), 새우젓(새우:국내산), '
    '바지락살(중국산), 채소류(국산), 국용채소류(국산/단,기후변화 등 이슈로 국산 수급이 어려울경우:중국산)\n\n'
    '*위의 메뉴는 재료 수급 사정에 따라 변경 될 수 있습니다\n\n'
    '*알레르기 정보 - 1.난류 2.우유 3.메밀 4.견과류(땅콩.아몬드.잣.코코넛등) 5.대두 6.밀 7.고등어 '
    '8.게 9.새우 10.돼지고기 11.복숭아 12.토마토 13.아황산류 14.호두 15.닭고기 16.쇠고기 \n'
    '17.오징어 18.조개류(굴.전복.홍합 포함) 19.파인애플 20.키위 21.참깨\n'
    '영양사 : '
)

MED = Side(style='medium', color='FF000000')
THIN = Side(style='thin', color='FF000000')
NONE_ = Side(style=None)

WD = ['월', '화', '수', '목', '금', '토', '일']
MENU_ROWS = 8                       # 한 주 블록의 메뉴 행 수 (원본과 동일)
ROW_ORDER = ['밥', '메인', '서브1', '서브2', '김치', '국']
# 일자별 시트의 '구분' 표기 (원본 용어)
SLOT_LABEL = {'밥': '밥', '국': '국', '메인': '메인',
              '서브1': '반찬1', '서브2': '반찬2', '김치': '반찬3'}
DAILY_ORDER = ['밥', '국', '메인', '서브1', '서브2', '김치']


def bd(l=THIN, r=THIN, t=THIN, b=THIN):
    return Border(left=l, right=r, top=t, bottom=b)


def week_blocks(days):
    """영업일을 주 단위(월~금)로 묶는다."""
    weeks = collections.OrderedDict()
    for d in sorted(days):
        key = d - datetime.timedelta(days=d.weekday())
        weeks.setdefault(key, {})[d.weekday()] = d
    return weeks


def day_menu(data, plan, d, line, order=None):
    """하루치 [(표기명, 자리, 보조여부)] — 보조는 부모 바로 아래."""
    out = []
    day = plan[d]
    for slot in (order or ROW_ORDER):
        rid = day.get(slot)
        if not rid: continue
        out.append((display_name(data, rid, line), slot, False))
        side = day.get(f'_보조_{slot}')
        if side: out.append((side, slot, True))
    if day.get('_디저트'):
        out.append((day['_디저트'], '디저트', False))
    return out


def recipe_by_name(data, name):
    """표기명 → 마스터 행. 별칭·보조('& ')도 찾는다."""
    if not name:
        return {}
    rid = data.rid_by_rep.get(name) or data.rid_of.get(name)
    if not rid:
        for a in getattr(data, "alias_rows", []):
            if a.get("alias") == name:
                rid = a.get("recipe_id")
                break
    if not rid and str(name).lstrip().startswith("&"):
        stripped = str(name).lstrip("&").strip()
        if stripped != name:
            return recipe_by_name(data, stripped)
    return data.master.get(rid, {}) if rid else {}


def allergy_label(master_row):
    raw = (master_row or {}).get("allergy") or ""
    if not raw or str(raw).strip() in {"0", "-", "."}:
        return "0"
    codes = str(raw).strip().strip(".")
    return f".{codes}." if codes else "0"


# ============================================================
# 레시피북 시트 — 원본과 동일한 열 배치 (수식 오프셋이 여기에 의존)
#   A No. / B 품목 / C 품명 / D 온라인(g) / E 급식(g)
#   F 온라인 중/대(EA) / G 급식(EA) / H 자재사용내역 / I 알러지표기 / J 메모
# ============================================================
def sheet_recipe(wb, data, extra_names=()):
    ws = wb.create_sheet('레시피북')
    hdr = ['No.', '품목', '품명', '온라인(g)', '급식(g)', '온라인\n중/대(EA)',
           '급식(EA)', '자재사용내역', '알러지표기', '']
    ws.append(hdr)
    rows = [m for m in data.master.values() if m['status'].startswith('활성')]
    have = {m['rep'] for m in rows}
    out = [(m['rep'], m) for m in rows]
    # 별칭(성인 표기 등)도 원본 레시피북처럼 각각 한 행으로 등재
    alias_rid = {}
    for rid, lst in data.alias_by_rid.items():
        for a in lst: alias_rid[a['alias']] = rid
    for nm in extra_names:
        if not nm or nm in have: continue
        rid = data.rid_by_rep.get(nm) or alias_rid.get(nm)
        if rid:
            out.append((nm, data.master[rid])); have.add(nm)
    out.sort(key=lambda t: t[0])
    for i, (nm, m) in enumerate(out, 1):
        ws.append([i, '', nm, m['weight_g'] or '', m['weight_g'] or '',
                   '', '', m['text'], m['allergy'], m['memo']])
    for c in range(1, 11):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(name=FONT, size=9, bold=True)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = bd(t=MED, b=MED)
    for r in range(2, ws.max_row + 1):
        for c in range(1, 11):
            cell = ws.cell(row=r, column=c)
            cell.font = Font(name=FONT, size=9)
            cell.alignment = Alignment(vertical='center',
                                       horizontal='left' if c in (8, 10) else 'center')
    for col, w in zip('ABCDEFGHIJ', [5, 8, 24, 10, 9, 11, 9, 70, 16, 30]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'D2'
    ws.row_dimensions[1].height = 30
    return ws.max_row


# ============================================================
# 식단표 시트 — 원본 '유아식단표' 서식 복제
# ============================================================
def sheet_menu(wb, data, plan, title, line, nrec):
    ws = wb.create_sheet(title)
    month = sorted(plan)[0].month

    # 제목
    ws.merge_cells('A1:K1')
    t = ws['A1']
    t.value = f'           {month:02d}월 식단표'
    t.font = Font(name=FONT, size=48, bold=True)
    t.fill = PatternFill('solid', fgColor=GREEN)
    t.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 120
    for c in range(1, 12):
        ws.cell(row=1, column=c).border = bd(MED, MED, MED, MED)

    weeks = week_blocks(plan.keys())
    r = 2
    for wi, (wk, dmap) in enumerate(weeks.items(), 1):
        # ── 요일 행 (첫 주에만 원본처럼 표기, 이후 주는 날짜 행부터)
        if wi == 1:
            ws.cell(row=r, column=1, value='요일')
            for i in range(5):
                c = 2 + i * 2
                ws.merge_cells(start_row=r, start_column=c, end_row=r, end_column=c + 1)
                ws.cell(row=r, column=c, value=WD[i])
            for c in range(1, 12):
                cell = ws.cell(row=r, column=c)
                cell.font = Font(name=FONT, size=14, bold=(c == 1))
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = bd(MED, MED, MED, MED)
            ws.row_dimensions[r].height = 24.95
            r += 1

        # ── 날짜 행
        ws.cell(row=r, column=1, value='날짜')
        for i in range(5):
            c = 2 + i * 2
            ws.merge_cells(start_row=r, start_column=c, end_row=r, end_column=c + 1)
            d = dmap.get(i)
            cell = ws.cell(row=r, column=c)
            if d:
                cell.value = d
                cell.number_format = 'm"월"\\ d"일";@'
        for c in range(1, 12):
            cell = ws.cell(row=r, column=c)
            cell.font = Font(name=FONT, size=11, bold=True)
            cell.fill = PatternFill('solid', fgColor=ORANGE)
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = bd(MED, MED, MED, MED)
        ws.row_dimensions[r].height = 24.95
        r += 1

        # ── 헤더 행
        ws.cell(row=r, column=1, value='주차')
        for i in range(5):
            c = 2 + i * 2
            ws.cell(row=r, column=c, value='메뉴')
            ws.cell(row=r, column=c + 1, value='알레르기표기')
        for c in range(1, 12):
            cell = ws.cell(row=r, column=c)
            cell.font = Font(name=FONT, size=11 if c == 1 else 9, bold=True)
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = bd(MED, MED, MED, MED)
        ws.row_dimensions[r].height = 20.1
        r += 1

        # ── 메뉴 8행
        start = r
        cols = {i: day_menu(data, plan, dmap[i], line) for i in dmap}
        for k in range(MENU_ROWS):
            for i in range(5):
                c = 2 + i * 2
                lst = cols.get(i, [])
                mcell = ws.cell(row=r, column=c)
                acell = ws.cell(row=r, column=c + 1)
                if k < len(lst):
                    nm, slot, is_side = lst[k]
                    mcell.value = nm
                    acell.value = allergy_label(recipe_by_name(data, nm))
                mcell.font = Font(name=FONT, size=9)
                mcell.alignment = Alignment(horizontal='center', vertical='center')
                acell.font = Font(name=FONT, size=8, bold=True)
                acell.alignment = Alignment(horizontal='left', vertical='center')
                lb = MED if i == 0 else THIN
                mcell.border = bd(MED, NONE_, THIN, THIN)
                acell.border = bd(NONE_, MED, THIN, THIN)
            ws.cell(row=r, column=1).border = bd(MED, MED, THIN, THIN)
            ws.row_dimensions[r].height = 20.1
            r += 1
        ws.merge_cells(start_row=start, start_column=1, end_row=r - 1, end_column=1)
        a = ws.cell(row=start, column=1)
        a.value = f'{wi}주'
        a.font = Font(name=FONT, size=11, bold=True)
        a.alignment = Alignment(horizontal='center', vertical='center')
        # 블록 하단 굵은 선
        for c in range(1, 12):
            cur = ws.cell(row=r - 1, column=c)
            cur.border = Border(left=cur.border.left, right=cur.border.right,
                                top=cur.border.top, bottom=MED)

    # ── 하단 범례 (원본 A53 블록)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=11)
    lg = ws.cell(row=r, column=1, value=LEGEND)
    lg.font = Font(name=FONT, size=11, bold=True)
    lg.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.row_dimensions[r].height = 150
    for c in range(1, 12):
        ws.cell(row=r, column=c).border = bd(MED, MED, MED, MED)

    for col, w in zip('ABCDEFGHIJK',
                      [6.6, 15.8, 16.1, 16.0, 15.5, 14.2, 13.1, 14.6, 14.4, 16.2, 14.0]):
        ws.column_dimensions[col].width = w
    # 인쇄 설정 — 원본과 동일 (A4 세로, 1페이지 맞춤)
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.paperSize = 9
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.page_margins.left = ws.page_margins.right = 0.7
    ws.print_area = f'A1:K{r}'
    return ws


# ============================================================
# 일자별 시트 — 원본 '07-01' 서식 복제
# ============================================================
DAILY_HDR = ['출고일', '구분', '품명', '중량(g)', '수량(장)', '자재사용내역',
             '알러지 표기', '배송시점 ', '제공인원', '총생산량(Kg)', '메 모']

ADULT_PLAN = {}


def sheet_daily(wb, data, plan, d, nrec):
    name = d.strftime('%m-%d')
    ws = wb.create_sheet(name)

    ws.merge_cells('B1:L1')
    t = ws['B1']
    t.value = f'{d.isoformat()}({WD[d.weekday()]})'
    t.font = Font(name=FONT, size=24, bold=True)
    t.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 39.95

    for i, h in enumerate(DAILY_HDR):
        cell = ws.cell(row=2, column=2 + i, value=h)
        cell.font = Font(name=FONT, size=9 if i != 2 and i != 5 else 10, bold=(i != 0))
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = bd(THIN, THIN, MED, MED)
    ws.row_dimensions[2].height = 24.95

    menu = day_menu(data, plan, d, '유아', DAILY_ORDER)
    menu_a = day_menu(data, ADULT_PLAN, d, '성인', DAILY_ORDER)

    r = 3
    for line_name, items, ship, fill in [
            ('중식', menu, f'{d.isoformat()} 09:30~', BLUE),
            ('글로벌\n리더스\n.\n석식', menu_a, f'{d.isoformat()} 14:30~', BLUE)]:
        start = r
        for nm, slot, is_side in items:
            m = recipe_by_name(data, nm)
            ws.cell(row=r, column=3, value=('' if is_side else SLOT_LABEL.get(slot, slot)))
            ws.cell(row=r, column=4, value=nm)
            ws.cell(row=r, column=5, value=m.get('weight_g') or '')
            ws.cell(row=r, column=7, value=m.get('text') or m.get('ingredients') or '')
            ws.cell(row=r, column=8, value=allergy_label(m) if m else '')
            ws.cell(row=r, column=9, value=ship)
            ws.cell(row=r, column=12, value=m.get('memo') or '')
            # 제공인원 K / 총생산량 L 은 담당자 입력란
            ws.cell(row=r, column=10).fill = PatternFill('solid', fgColor=YELLOW)
            ws.cell(row=r, column=11, value=f'=IF($E{r}="","",IF($J{r}="","",$E{r}*$J{r}))')
            r += 1
        # 보존식 행
        ws.cell(row=r, column=3, value='보존식')
        ws.cell(row=r, column=10, value=1)
        ws.cell(row=r, column=11, value=0.25)
        r += 1
        # 라인 셀 병합
        ws.merge_cells(start_row=start, start_column=2, end_row=r - 1, end_column=2)
        b = ws.cell(row=start, column=2)
        b.value = line_name
        b.font = Font(name=FONT, size=9, bold=True)
        b.fill = PatternFill('solid', fgColor=fill)
        b.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        for rr in range(start, r):
            ws.cell(row=rr, column=2).fill = PatternFill('solid', fgColor=fill)

    # 공통 서식
    for rr in range(3, r):
        ws.row_dimensions[rr].height = 39.95
        for c in range(2, 13):
            cell = ws.cell(row=rr, column=c)
            if cell.font.size is None or c != 2:
                cell.font = Font(name=FONT, size=10 if c in (4, 5, 7) else 9,
                                 bold=(c in (4, 8, 9, 10, 11)))
            cell.alignment = Alignment(
                horizontal='left' if c in (4, 7, 12) else 'center',
                vertical='center', wrap_text=(c in (7, 12)))
            cell.border = bd(THIN, THIN, THIN, THIN)

    for col, w in zip('BCDEFGHIJKL',
                      [7.8, 5.8, 22.6, 8.6, 9.6, 55.6, 16.5, 27.2, 7.9, 10.6, 13.8]):
        ws.column_dimensions[col].width = w
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = 9
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.print_area = f'A1:L{r - 1}'
    return ws


def sheet_howto(wb, plan, fails):
    ws = wb.create_sheet('HowToUse')
    rows = [
        ['키즈락 식단표 초안 — 자동 생성본', '', ''],
        ['', '', ''],
        [1, '이 파일은 기존 생산일지와 동일한 구조로 자동 생성된 초안이다.', ''],
        [2, '"레시피북" 시트에 자재사용내역·알러지·중량이 들어 있고,', ''],
        ['', '   식단표·일자별 시트에도 같은 값을 직접 채워 두었다. (미리보기/엑셀 앱에서 수식이 비지 않게)', ''],
        [3, '메뉴를 바꾼 뒤에는 레시피북에서 해당 품명을 찾아 알러지·자재를 맞춰 적는다.', ''],
        ['', '   신메뉴는 레시피북에 먼저 등록한다.', ''],
        [4, '노란색 칸(제공인원)은 담당자 입력란이다. 입력하면 총생산량이 자동 계산된다.', ''],
        [5, "'&'로 시작하는 항목은 바로 위 메뉴에 딸린 보조(소스·드레싱)이며 자리를 차지하지 않는다.", ''],
        [6, '생일파티 특식일(3주차 금요일)은 국 없이 볶음밥+스파게티+치킨+피클+디저트로 구성된다.', ''],
        [7, '자동 생성은 초안이다. 제철 재료·신메뉴·납품처 요구·조리실 사정은 담당자가 반영한다.', ''],
        ['', '', ''],
        ['생성 영업일', len(plan), ''],
        ['배치 실패일', len(fails), str(fails) if fails else '없음'],
    ]
    for row in rows: ws.append(row)
    ws['A1'].font = Font(name=FONT, size=14, bold=True)
    for r in range(2, ws.max_row + 1):
        for c in range(1, 4):
            ws.cell(row=r, column=c).font = Font(name=FONT, size=10)
            ws.cell(row=r, column=c).alignment = Alignment(vertical='center')
    ws.column_dimensions['A'].width = 14
    ws.column_dimensions['B'].width = 95
    ws.column_dimensions['C'].width = 20
    return ws


def sheet_reason(wb, data, plan, notes, aplan=None, anote=None):
    ws = wb.create_sheet('선택근거')
    hdr = ['날짜', '요일', '자리', '표기명', '레시피ID', '주재료', '조리방식',
           '알레르기', '완제품', '선택 근거', '성인·초등 표기', '성인식 변형 사유']
    ws.append(hdr)
    for d in sorted(plan):
        for slot in ROW_ORDER:
            rid = plan[d].get(slot)
            if not rid: continue
            m = data.master[rid]
            ws.append([d.isoformat(), WD[d.weekday()], slot,
                       display_name(data, rid, '유아'), rid, m['protein'] or '-',
                       m['cook'], m['allergy'], 'O' if m['ready'] else '',
                       notes[d].get(slot, ''),
                       display_name(data, (aplan or {}).get(d, {}).get(slot, rid), '성인'),
                       (anote or {}).get(d, {}).get(slot, '')])
            side = plan[d].get(f'_보조_{slot}')
            if side:
                srid = data.rid_by_rep.get(side)
                ws.append([d.isoformat(), WD[d.weekday()], f'└ {slot} 보조', side,
                           srid or '', '-', '-',
                           data.master.get(srid, {}).get('allergy', ''), '',
                           notes[d].get(f'_보조_{slot}', '')])
    for c in range(1, len(hdr) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = PatternFill('solid', fgColor='FF1F3864')
        cell.font = Font(name=FONT, size=10, bold=True, color='FFFFFFFF')
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:L{ws.max_row}'
    for col, w in zip('ABCDEFGHIJKL', [12, 6, 12, 26, 10, 14, 10, 16, 8, 62, 26, 34]):
        ws.column_dimensions[col].width = w


def build(ym, out_path, days=None, blacklist=(), repo=None):
    """한 달치 생산일지 초안 워크북을 만든다."""
    data = repo or Repository()
    y, m = int(ym[:4]), int(ym[5:7])

    kid_plan, st = generate_month(data, y, m, days=days,
                                  blacklist=blacklist, line='유아')
    attach_sides(data, kid_plan)

    # 성인·초등 변형본 — 과거 6개월 유아↔성인 비교로 학습한 교체쌍 적용
    swap, seen, dropped = build_swap_map(data, f'{ym}-01')
    print(f'  성인식 변형쌍 {len(swap)}건 학습 / 메뉴 자체 교체 {dropped}건 제외')
    adult_plan = to_adult(data, kid_plan, swap, seen)
    print(f'  성인식 상이율 {divergence(kid_plan, adult_plan)}%')

    plan, notes = flatten(kid_plan)
    aplan, anote = flatten(adult_plan)
    fails = kid_plan.failures

    global ADULT_PLAN          # 일자별 시트가 참조하는 성인식 편성
    ADULT_PLAN = aplan

    wb = openpyxl.Workbook(); wb.remove(wb.active)
    placeholder_a = wb.create_sheet('글로벌리더스&석식식단표')
    placeholder_k = wb.create_sheet('유아식단표')
    used = set()
    for src in (plan, aplan):
        for d in src:
            for k, v in src[d].items():
                if k.startswith('_보조_') or k == '_디저트':
                    used.add(v)
                elif not k.startswith('_') and v in data.master:
                    used.add(data.master[v]['rep'])
                    used.add(display_name(data, v, '유아'))
                    used.add(display_name(data, v, '성인'))
    nrec = sheet_recipe(wb, data, used)
    wb.remove(placeholder_a); wb.remove(placeholder_k)

    sheet_menu(wb, data, aplan, '글로벌리더스&석식식단표', '성인', nrec)
    sheet_menu(wb, data, plan, '유아식단표', '유아', nrec)
    for d in sorted(plan):
        sheet_daily(wb, data, plan, d, nrec)
    sheet_reason(wb, data, plan, notes, aplan, anote)
    sheet_howto(wb, plan, fails)

    order = ['글로벌리더스&석식식단표', '유아식단표', '레시피북'] + \
            [d.strftime('%m-%d') for d in sorted(plan)] + ['선택근거', 'HowToUse']
    wb._sheets = [wb[n] for n in order]
    wb.save(out_path)
    return kid_plan, adult_plan, fails





if __name__ == '__main__':
    ym = sys.argv[1] if len(sys.argv) > 1 else '2026-10'
    hol = [x for x in sys.argv[2].split(',') if x] if len(sys.argv) > 2 else []
    y, m = int(ym[:4]), int(ym[5:7])
    days = month_business_days(y, m, hol)
    plan, notes, fails = build(ym, f_KR + '/{m:02d}월 생산일지_초안.xlsx', days=days)
    print(f'생성: {len(plan)}영업일 / 실패 {len(fails)}일 / 공휴일 제외 {hol}')
