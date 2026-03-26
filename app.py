"""
한국 주식 추천 시스템 — Streamlit 웹앱
"""
import os
import datetime
import io
import pandas as pd
import streamlit as st
import OpenDartReader

from data_fetcher import get_stock_list, get_dart_corp_codes, collect_all
from screener import apply_screening
from scorer import calculate_score

st.set_page_config(page_title="한국 주식 추천 시스템", page_icon="📈", layout="wide")


# ── Streamlit Cloud Secrets 또는 환경변수에서 API 키 로드 ──
def load_api_key() -> str:
    try:
        return st.secrets["DART_API_KEY"]
    except Exception:
        return os.environ.get("DART_API_KEY", "")


# ── 사이드바: 스크리닝 기준값 조절 ──
st.sidebar.title("⚙️ 스크리닝 기준값")

min_op_margin = st.sidebar.slider("최소 영업이익률 (%)", 0, 30, 10) / 100
max_per = st.sidebar.slider("최대 PER (배)", 5, 50, 20)
min_rev_growth = st.sidebar.slider("최소 매출 성장률 (%)", 0, 50, 10) / 100
max_debt_ratio = st.sidebar.slider("최대 부채비율 (%)", 50, 500, 200)

screening_override = {
    "min_operating_margin": min_op_margin,
    "max_per": max_per,
    "min_revenue_growth": min_rev_growth,
    "max_debt_ratio": max_debt_ratio,
}

# DART API 키 입력 (Secrets에 없을 때 UI에서 입력)
api_key = load_api_key()
if not api_key:
    api_key = st.sidebar.text_input("DART API 키 입력", type="password",
                                     help="opendart.fss.or.kr에서 무료 발급")

st.sidebar.markdown("---")
st.sidebar.markdown("**테스트 모드**")
test_mode = st.sidebar.checkbox("빠른 테스트 (상위 200개 종목만)", value=False)
max_stocks = 200 if test_mode else None

# ── 메인 화면 ──
st.title("📈 한국 주식 추천 시스템")
st.caption("영업이익률·PER·매출성장률·부채비율 기준 정량 스크리닝 → 스코어링")

if not api_key:
    st.warning("사이드바에서 DART API 키를 입력하세요. (opendart.fss.or.kr 무료 발급)")
    st.stop()

# 실행 버튼
if st.button("🔍 분석 시작", type="primary"):
    # config 모듈의 스크리닝 기준값 동적 오버라이드
    import config
    config.SCREENING.update(screening_override)

    dart = OpenDartReader.OpenDartReader(api_key)

    with st.spinner("종목 리스트 수집 중..."):
        stock_list = get_stock_list()
        corp_code_map = get_dart_corp_codes(dart)

    st.info(f"총 {len(stock_list)}개 종목 대상 {'(테스트: 200개 제한)' if test_mode else ''}")

    # 진행률 바
    progress_bar = st.progress(0)
    status_text = st.empty()

    def progress_callback(current, total, name):
        pct = int(current / total * 100)
        progress_bar.progress(pct)
        status_text.text(f"수집 중: {current}/{total} — {name}")

    with st.spinner("재무 데이터 수집 중... (시간이 걸립니다)"):
        df_raw = collect_all(stock_list, dart, corp_code_map,
                             max_stocks=max_stocks,
                             progress_callback=progress_callback)

    progress_bar.empty()
    status_text.empty()

    if df_raw.empty:
        st.error("재무 데이터 수집 실패. DART API 키를 확인하세요.")
        st.stop()

    df_screened = apply_screening(df_raw)

    if df_screened.empty:
        st.warning("스크리닝 통과 종목이 없습니다. 사이드바에서 기준값을 완화해보세요.")
        st.stop()

    df_scored = calculate_score(df_screened)

    # ── 결과 표시 ──
    st.success(f"스크리닝 통과: **{len(df_scored)}개** 종목")

    # 표시용 포맷
    display = df_scored.copy()
    display.insert(0, "순위", range(1, len(display) + 1))
    display["영업이익률"] = (display["operating_margin"] * 100).round(1).astype(str) + "%"
    display["매출성장률"] = (display["revenue_growth"] * 100).round(1).astype(str) + "%"
    display["부채비율"] = display["debt_ratio"].round(1).astype(str) + "%"
    display["PER"] = display["per"].round(1)
    display["점수"] = display["score"]
    display = display.rename(columns={"name": "종목명", "market": "시장", "code": "종목코드"})

    show_cols = ["순위", "종목명", "시장", "점수", "영업이익률", "PER", "매출성장률", "부채비율"]
    st.dataframe(display[show_cols], use_container_width=True, hide_index=True)

    # Excel 다운로드
    output = io.BytesIO()
    df_scored.to_excel(output, index=False, engine="openpyxl")
    output.seek(0)
    date_str = datetime.date.today().strftime("%Y%m%d")
    st.download_button(
        label="📥 Excel 다운로드",
        data=output,
        file_name=f"추천종목_{date_str}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

else:
    st.info("사이드바에서 기준값을 설정하고 '분석 시작' 버튼을 누르세요.")
