# 한국 주식 추천 시스템

nubul0307 블로그 방법론 기반 — 정량 스크리닝 → 스코어링 → AI 사업보고서 분석

**Streamlit 앱**: https://jghn02-investment.streamlit.app (또는 Streamlit Cloud에서 확인)

---

## 아키텍처

```
[로컬] collect_data.py → financial_data.csv → GitHub push
[클라우드] app.py → CSV 읽기 → 즉시 스크리닝 (API 호출 없음)
```

실시간 API 호출 대신 사전 수집 CSV를 사용. Streamlit Cloud에서 DART API 직접 호출 시
ConnectTimeout이 발생해서 이 구조로 변경함.

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `collect_data.py` | **로컬 전용** 재무 데이터 수집 스크립트 |
| `app.py` | Streamlit 웹앱 (CSV 읽기 + 스크리닝 + AI 분석) |
| `config.py` | API 키, 스크리닝 기준값, 가중치 |
| `data_fetcher.py` | 종목 리스트 + 재무 데이터 수집 함수 |
| `screener.py` | 4개 조건 필터링 |
| `scorer.py` | 지표 정규화 → 가중합 점수 |
| `analyzer.py` | DART 사업보고서 섹션 추출 + Claude API 분석 |
| `financial_data.csv` | 수집된 재무 데이터 (분기 1회 갱신) |
| `corp_codes.csv` | DART 기업코드 전체 (115,596개, 수동 갱신) |

---

## 스크리닝 기준 (사이드바에서 조절 가능)

- 영업이익률 ≥ 10%
- PER ≤ 20배
- 매출 성장률 ≥ 10%
- 부채비율 ≤ 200%

---

## 데이터 수집 방법 (분기 1회 로컬 실행)

```bash
cd ~/Desktop/주식_추천_시스템

# 전체 수집 (~30~60분)
python3 collect_data.py

# 테스트용 200개만
python3 collect_data.py --max 200

# 수집 + GitHub 자동 push
python3 collect_data.py --push
```

**주의**: KRX API가 살아있을 때 실행해야 PER 데이터가 채워짐.
KRX API 다운 시 DART modify_date 폴백으로 종목 수집은 되지만 PER = NaN.

---

## 핵심 설계 결정

### FastDart 클래스
`OpenDartReader` 기본 `__init__`이 DART API에서 corp_codes를 다운로드하는데,
Streamlit Cloud(해외 서버)에서 ConnectTimeout 발생. → `corp_codes.csv`를 로컬에서 읽도록 서브클래스로 우회.

### bsns_year 로직
```python
# 4월 이전: 전전년도 (확정 보고서 보장), 4월 이후: 전년도
year - 2 if month < 4 else year - 1
```

### PER 수집
`fdr.StockListing()` 루프 안에서 매번 호출하면 KRX API 과부하 → 루프 전에 한 번만 `build_per_map()`으로 수집.

### PER NaN 처리
스크리너: NaN PER 종목은 PER 조건 통과 처리 (데이터 없다고 제외 안 함)
스코어러: NaN → 중앙값으로 대체 후 정규화

---

## Streamlit Cloud Secrets 설정

```toml
DART_API_KEY = "..."
ANTHROPIC_API_KEY = "sk-ant-..."
GITHUB_TOKEN = "ghp_..."   # corp_codes 갱신 버튼용 (선택)
```

---

## TODO / 알려진 이슈

- [ ] KRX API 복구 후 재수집 필요 (현재 PER 대부분 NaN)
- [ ] AI 분석은 상위 10~20개 종목에만 사용 권장 (크레딧 절약)
- [ ] `analyzer.py`의 `FastDart` import가 누락되어 있음 → `from data_fetcher import FastDart` 추가 필요
