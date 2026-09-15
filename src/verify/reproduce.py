# -*- coding: utf-8 -*-
# 이 모듈은 단독 실행용 파이프라인 단계다.
#   python -m src.extract.reproduce
# 경로는 src/config/paths.py 한 곳에서만 정의한다.
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from src.config import paths
paths.ensure_dirs()
_KR = str(paths.DATA_DIR)
_SRC = str(paths.DATA_DIR)

# -*- coding: utf-8 -*-
"""9단계 — 재현 테스트: 생성본 vs 실제 편성 4개 지표 대조"""
import sys, datetime, collections
from src.config.constants import SLOTS, ROTATION
from src.domain.repository import Repository
from src.rules.pools import build_pools, is_donburi
from src.rules.hard import violates
from src.rules.state import PlacementState as State
from src.planner.placer import generate_month
from src.planner.labels import attach_sides
from src.export.adapters import flatten


def actual_month(data, ym, line='유아'):
    out = collections.defaultdict(dict)
    for d, ln, sl, rid, nm in data.history:
        if d[:7] == ym and ln == line and sl:
            out[datetime.date.fromisoformat(d)][sl] = rid
    return dict(out)


def check_hard(data, plan, label):
    """생성본/실제본 각각의 하드 제약 위반 건수"""
    st = State(data, '1900-01-01')
    v = []
    ready_main = donburi = 0
    for d in sorted(plan):
        day = {k: r for k, r in plan[d].items() if not k.startswith('_') and r in data.master}
        # 주재료 중복
        keys = [k for k in ('메인', '서브1', '서브2', '국') if k in day]
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = day[keys[i]], day[keys[j]]
                pa = set(x.strip() for x in data.master[a]['protein'].split(',') if x.strip())
                pb = set(x.strip() for x in data.master[b]['protein'].split(',') if x.strip())
                if pa & pb:
                    v.append((d, '주재료중복',
                              f'{keys[i]}:{data.master[a]["rep"]} ↔ {keys[j]}:{data.master[b]["rep"]} ({",".join(pa & pb)})'))
        # 튀김 2개
        fry = [data.master[r]['rep'] for r in day.values() if data.master[r]['cook'] == '튀김']
        if len(fry) > 1: v.append((d, '튀김2개', ', '.join(fry)))
        # 월 상한 집계
        if '메인' in day:
            if data.master[day['메인']]['ready']: ready_main += 1
            if is_donburi(data.master[day['메인']]): donburi += 1
    if ready_main > 3: v.append((None, '완조리메인 월상한', f'{ready_main}일 (상한 3)'))
    if donburi > 2: v.append((None, '덮밥소스 월상한', f'{donburi}일 (상한 2)'))
    return v, ready_main, donburi


def compare(data, gen, act):
    days = sorted(set(gen) & set(act))
    tot = hit = 0
    prot_hit = cook_hit = prot_tot = 0
    detail = []
    for d in days:
        for s in SLOTS:
            g, a = gen[d].get(s), act[d].get(s)
            if not a: continue
            tot += 1
            ok = (g == a)
            hit += ok
            if g and a:
                pg = data.master[g]['protein']; pa = data.master[a]['protein']
                cg = data.master[g]['cook'];    ca = data.master[a]['cook']
                prot_tot += 1
                prot_hit += (pg == pa)
                cook_hit += (cg == ca)
            detail.append((d, s,
                           data.master[g]['rep'] if g else '-',
                           data.master[a]['rep'] if a else '-', ok))
    # 월 단위 메뉴 집합 일치 — 날짜는 달라도 같은 메뉴 풀에서 골랐는가
    setm = {}
    for s in SLOTS:
        gs = {gen[d].get(s) for d in days if gen[d].get(s)}
        as_ = {act[d].get(s) for d in days if act[d].get(s)}
        if as_:
            setm[s] = (len(gs & as_), len(as_))
    su = sum(v[0] for v in setm.values()); sv = sum(v[1] for v in setm.values())
    return {
        'slots': tot, 'exact': hit,
        'set_rate': su / sv if sv else 0, 'set_hit': su, 'set_tot': sv,
        'set_by_slot': setm,
        'exact_rate': hit / tot if tot else 0,
        'protein_rate': prot_hit / prot_tot if prot_tot else 0,
        'cook_rate': cook_hit / prot_tot if prot_tot else 0,
    }, detail


def run(ym, line='유아', verbose=True):
    data = Repository()
    y, m = int(ym[:4]), int(ym[5:7])
    act = actual_month(data, ym, line)
    days = sorted(act)
    if not days:
        print(f'{ym}: 실제 편성 데이터 없음'); return None
    month_plan, st = generate_month(data, y, m, days=days, line=line)
    attach_sides(data, month_plan)
    plan, notes = flatten(month_plan)
    fails = month_plan.failures

    gv, grm, gdb = check_hard(data, plan, '생성')
    av, arm, adb = check_hard(data, act, '실제')
    met, detail = compare(data, plan, act)

    if verbose:
        print(f'━━━ {ym} ({line}) 재현 테스트 ━━━')
        print(f'  영업일 {len(days)}일 / 배치 실패 {len(fails)}일 {fails if fails else ""}')
        print(f'  ① 칸 단위 일치   {met["exact"]}/{met["slots"]}  ({met["exact_rate"]*100:.1f}%)')
        print(f'  ② 하드 제약 위반  생성 {len(gv)}건 / 실제 {len(av)}건')
        print(f'  ③ 메뉴 집합 일치   {met["set_hit"]}/{met["set_tot"]}  ({met["set_rate"]*100:.1f}%)'
              f'   ← 날짜 무관, 같은 메뉴를 썼는가')
        print('     자리별: ' + ' · '.join(f'{k} {v[0]}/{v[1]}' for k, v in met['set_by_slot'].items()))
        print(f'  ④ 단백질 구성 일치 {met["protein_rate"]*100:.1f}%  ·  조리방식 일치 {met["cook_rate"]*100:.1f}%')
        print(f'  ⑤ 완조리 메인     생성 {grm}일 / 실제 {arm}일   (상한 3)')
        print(f'     덮밥소스        생성 {gdb}일 / 실제 {adb}일   (상한 2)')
        if gv:
            print('  ── 생성본 위반 상세')
            for x in gv[:8]: print('     ', x)
        if av:
            print('  ── 실제본 위반 상세 (담당자 편성)')
            for x in av[:8]: print('     ', x)
    return dict(ym=ym, metrics=met, gen_viol=gv, act_viol=av,
                plan=plan, notes=notes, actual=act, detail=detail, fails=fails)


if __name__ == '__main__':
    for ym in (sys.argv[1:] or ['2026-07', '2026-08']):
        run(ym); print()
