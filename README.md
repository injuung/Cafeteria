# 키즈락 식단표 자동 초안 생성기

더바른푸드 '키즈락' 브랜드의 월별 식단표(생산일지) 초안을 자동 생성한다.
과거 14개월치 생산일지에서 레시피 마스터를 만들고, 업무규칙·통계 기반 조합 룰에 따라
유아식/성인·석식 2개 라인의 한 달치 편성을 뽑아 기존 생산일지와 동일한 서식으로 출력한다.

## 구조

```
src/
├─ main.py                     CLI 진입점
├─ web/                        브라우저 화면 (python -m src.web)
├─ config/
│   ├─ paths.py                경로 정의 (여기 한 곳만 고치면 된다)
│   └─ constants.py            업무규칙 상수 — 값마다 출처 태그
├─ domain/
│   ├─ models.py               Recipe / DayPlan / MonthPlan
│   └─ repository.py           master·raw·groups json 로더 + 편성이력
├─ extract/                    원천 엑셀 → master.json (3단계 파이프라인)
│   ├─ step1_parse.py          생산일지 파싱 (편성원장·자재사용내역·알레르기)
│   ├─ step2_group.py          이름이 다른 동일 메뉴를 하나의 레시피 ID로 묶기
│   └─ step3_tag.py            단백질·조리방식·완제품·알레르기 태깅
├─ rules/
│   ├─ pools.py                자리별 후보 풀
│   ├─ state.py                배치 진행 상태 (로테이션·월간 상한 카운터)
│   ├─ hard.py                 하드 제약 — 걸리면 후보에서 제외
│   ├─ soft.py                 점수 함수 — 통과한 후보들의 우선순위
│   └─ combination.py          조합 기피 룰 (통계 근거 + 식사 대상 관점)
├─ planner/
│   ├─ calendar.py             특식일·도시락김 금요일 산출
│   ├─ feast.py                생일파티 특식 구성
│   ├─ placer.py               하루 6칸 배치 → 한 달치
│   ├─ labels.py               표기명 선택 + 보조('&') 메뉴 부착
│   └─ adult.py                성인·석식 변형
├─ export/
│   ├─ adapters.py             도메인 모델 → 출력기용 평면 dict
│   ├─ recipe_book.py          레시피북 마스터 xlsx
│   └─ production_sheet.py     생산일지 포맷 xlsx (원본과 동일 서식)
├─ analysis/
│   ├─ build_days.py           분석용 일자별 슬롯 테이블
│   └─ combination_stats.py    '나오지 않은 조합' 탐지 (기대값 대비 관측)
└─ verify/
    └─ reproduce.py            과거 달 재현 테스트
```

## 설치

```bash
git clone https://github.com/injuung/Cafeteria.git
cd Cafeteria
pip install -r requirements.txt
```

**원천 데이터가 저장소에 함께 들어 있다.** 별도 준비 없이 클론 직후 바로 돌아간다.
2025-08 ~ 2026-09 생산일지 14개월 + 식단표 14개월, 중간 산출 JSON 포함.
자세한 건 `data/README.md` 참고.

## 사용

웹 화면(달력에서 휴무를 고르고 초안을 만든 뒤 엑셀로 받음):

```bash
pip install -r requirements.txt
python -m src.web
```

브라우저에서 http://127.0.0.1:8000 을 연다. 이 컴퓨터에서만 열린다.

남에게 보여줄 공개 주소(GitHub Pages):

https://injuung.github.io/Cafeteria/

이 주소는 미리 만들어 둔 초안을 보여 주는 정적 페이지다. `main` 에 푸시하면 GitHub Actions 가 사이트를 다시 올린다.

명령줄:

```bash
python -m src.main pipeline          # 원천 엑셀 → data/master.json (재생성용, 이미 들어 있음)
python -m src.main master            # 레시피북 마스터 xlsx
python -m src.main plan 2026-11      # 11월 생산일지 초안
python -m src.main plan 2026-11 --holidays 2026-11-05,2026-11-06
python -m src.main analyze           # 조합 분석 리포트
python -m src.main rules             # 조합 기피 룰 목록
python -m src.main verify 2026-07    # 과거 달 재현 테스트
```

## 설계 메모

**레시피 ID vs 별칭.** 같은 음식을 '얼큰순두부찌개'와 '매콤순두부찌개'처럼 다르게 적어
체감 다양성을 만드는 것이 이 사업장의 실제 운영 방식이다. 그래서 정체성(중복·로테이션 판정)은
레시피 ID로 보고, 화면에 찍히는 이름은 별칭 풀에서 고른다. `step2_group.py` 가 ID를 만들고
`planner/labels.py` 가 표기를 고른다.

**하드 제약과 소프트 점수의 분리.** 하드는 위반 시 후보에서 빼고, 소프트는 감점만 한다.
하드를 늘리면 배치 실패가 늘고, 소프트를 늘리면 규칙이 무시된다. 새 규칙을 추가할 때는
`verify` 로 과거 달 재현률이 떨어지지 않는지 먼저 확인한다.

**조합 기피 룰은 통계에서 왔다.** `rules/combination.py` 의 9개 룰은 1년치 실제 편성에서
'기대값 대비 한 번도 나오지 않은' 조합만 추린 것이다. 표본 부족으로 인한 빈칸과 구분하기 위해
독립가정 기대값과 포아송 P(0) 을 함께 계산한다 (`analysis/combination_stats.py`).
근거 문구는 각 룰의 `evidence` 필드에 그대로 남아 있다.

**상수에는 출처 태그가 붙어 있다.** `config/constants.py` 의 모든 값은
`[확정]`(담당자 회신) / `[문서]`(인터뷰 정리) / `[관측]`(데이터) / `[추정]`(구현상 판단)
중 하나로 표시된다. `[추정]` 은 전부 튜닝·확인 대상이다.

## 최종 배포 형태

이 파이썬 구현은 규칙을 확정하고 검증하기 위한 참조 구현이다.
실제 운영은 담당자 구글 계정의 Apps Script 로 옮기며, 그때의 제약(실행 6분 제한 등)은
`docs/명세_2_구현.md` 에 정리돼 있다.


## 현재 상태

| 항목 | 결과 |
|---|---|
| 2026-11 초안 생성 | 배치 실패 0건, 완조리 메인 2일, 성인식 상이율 1.6% |
| 재현 테스트 2026-07 | 메뉴 집합 일치 61.1%, 하드 제약 위반 생성 0건 / 실제 3건 |
| 재현 테스트 2026-08 | 메뉴 집합 일치 52.3%, 하드 제약 위반 생성 0건 / 실제 3건 |

'칸 단위 일치'가 5~8%로 낮은 것은 정상이다. 같은 규칙 안에서도 어느 날 무엇을 놓을지는
자유도가 크기 때문이고, 실제로 봐야 할 지표는 **③ 메뉴 집합 일치**(같은 메뉴 풀에서 골랐는가)와
**② 하드 제약 위반**(규칙을 어기지 않았는가)이다.

## 남은 일

- 인터뷰 문서 §3-3 (조리 형태별 조합 규칙) 미구현 — 통계 룰이 일부 대체하고 있으나 원문 대조 필요
- `config/constants.py` 의 `WEIGHT` 9개 값이 전부 `[추정]` — 튜닝 대상
- 성인식 변형 학습쌍이 5건뿐 — 유아/성인 대조 데이터가 80일치라 표본이 얇다
