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


# ── API 키 로드 ──
def load_secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, "")


# ── 세션 상태 초기화 ──
if "df_scored" not in st.session_state:
    st.session_state.df_scored = None
if "dart" not in st.session_state:
    st.session_state.dart = None
if "corp_code_map" not in st.session_state:
    st.session_state.corp_code_map = None
if "selected_stock" not in st.session_state:
    st.session_state.selected_stock = None


# ── 사이드바 ──
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

st.sidebar.markdown("---")

# DART API 키
dart_api_key = load_secret("DART_API_KEY")
if not dart_api_key:
    dart_api_key = st.sidebar.text_input("DART API 키", type="password",
                                          help="opendart.fss.or.kr 무료 발급")

# Claude API 키
claude_api_key = load_secret("ANTHROPIC_API_KEY")
if not claude_api_key:
    claude_api_key = st.sidebar.text_input("Claude API 키", type="password",
                                            help="console.anthropic.com에서 발급")

st.sidebar.markdown("---")
st.sidebar.markdown("**테스트 모드**")
test_mode = st.sidebar.checkbox("빠른 테스트 (상위 200개 종목만)", value=False)
max_stocks = 200 if test_mode else None


# ── 메인 화면 ──
st.title("📈 한국 주식 추천 시스템")
st.caption("영업이익률·PER·매출성장률·부채비율 기준 정량 스크리닝 → 스코어링 → AI 사업보고서 분석")

if not dart_api_key:
    st.warning("사이드바에서 DART API 키를 입력하세요.")
    st.stop()


# ══════════════════════════════════════════
# 탭 구조: 스크리닝 / 상세 분석
# ══════════════════════════════════════════
tab_screen, tab_detail = st.tabs(["📊 스크리닝 결과", "🔬 종목 상세 분석"])


# ── Tab 1: 스크리닝 ──
with tab_screen:
    if st.button("🔍 분석 시작", type="primary"):
        import config
        config.SCREENING.update(screening_override)

        dart = OpenDartReader.OpenDartReader(dart_api_key)
        st.session_state.dart = dart

        with st.spinner("종목 리스트 수집 중..."):
            stock_list = get_stock_list()
            corp_code_map = get_dart_corp_codes(dart)
            st.session_state.corp_code_map = corp_code_map

        st.info(f"총 {len(stock_list)}개 종목 대상 {'(테스트: 200개 제한)' if test_mode else ''}")

        progress_bar = st.progress(0)
        status_text = st.empty()

        def progress_callback(current, total, name):
            progress_bar.progress(int(current / total * 100))
            status_text.text(f"수집 중: {current}/{total} — {name}")

        with st.spinner("재무 데이터 수집 중..."):
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
            st.warning("스크리닝 통과 종목 없음. 기준값을 완화해보세요.")
            st.stop()

        st.session_state.df_scored = calculate_score(df_screened)

    # 결과 테이블
    if st.session_state.df_scored is not None:
        df = st.session_state.df_scored
        st.success(f"스크리닝 통과: **{len(df)}개** 종목")

        display = df.copy()
        display.insert(0, "순위", range(1, len(display) + 1))
        display["영업이익률"] = (display["operating_margin"] * 100).round(1).astype(str) + "%"
        display["매출성장률"] = (display["revenue_growth"] * 100).round(1).astype(str) + "%"
        display["부채비율"] = display["debt_ratio"].round(1).astype(str) + "%"
        display["PER"] = display["per"].round(1)
        display["점수"] = display["score"]
        display = display.rename(columns={"name": "종목명", "market": "시장", "code": "종목코드"})

        show_cols = ["순위", "종목명", "시장", "점수", "영업이익률", "PER", "매출성장률", "부채비율"]
        st.dataframe(display[show_cols], use_container_width=True, hide_index=True)

        # 종목 선택 → 상세 분석 탭으로 연결
        st.markdown("---")
        st.markdown("**상세 분석할 종목 선택**")
        col1, col2 = st.columns([3, 1])
        with col1:
            names = df["name"].tolist()
            selected = st.selectbox("종목 선택", names, label_visibility="collapsed")
        with col2:
            if st.button("🔬 AI 분석", type="secondary"):
                st.session_state.selected_stock = df[df["name"] == selected].iloc[0].to_dict()
                st.info("'종목 상세 분석' 탭에서 결과를 확인하세요.")

        # Excel 다운로드
        output = io.BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        output.seek(0)
        date_str = datetime.date.today().strftime("%Y%m%d")
        st.download_button(
            label="📥 Excel 다운로드",
            data=output,
            file_name=f"추천종목_{date_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.info("'분석 시작' 버튼을 눌러 스크리닝을 실행하세요.")


# ── Tab 2: 상세 분석 ──
with tab_detail:
    stock = st.session_state.selected_stock

    if stock is None:
        st.info("스크리닝 탭에서 종목을 선택하고 'AI 분석' 버튼을 누르세요.")
        st.stop()

    st.subheader(f"🔬 {stock['name']} ({stock['code']}) — 사업보고서 AI 분석")

    # 기본 지표 요약
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("점수", f"{stock['score']:.1f}")
    m2.metric("영업이익률", f"{stock['operating_margin']*100:.1f}%")
    m3.metric("PER", f"{stock['per']:.1f}배")
    m4.metric("매출성장률", f"{stock['revenue_growth']*100:.1f}%")
    m5.metric("부채비율", f"{stock['debt_ratio']:.1f}%")

    st.markdown("---")

    if not claude_api_key:
        st.warning("사이드바에서 Claude API 키를 입력하면 AI 분석이 활성화됩니다.")
        st.stop()

    if st.button("📄 사업보고서 AI 분석 실행", type="primary"):
        dart = st.session_state.dart
        corp_code_map = st.session_state.corp_code_map

        if dart is None or corp_code_map is None:
            st.error("먼저 스크리닝 탭에서 '분석 시작'을 실행하세요.")
            st.stop()

        code = stock["code"]
        name = stock["name"]

        if code not in corp_code_map.index:
            st.error("DART 기업코드를 찾을 수 없습니다.")
            st.stop()

        corp_code = corp_code_map.loc[code, "corp_code"]

        from analyzer import run_analysis
        with st.spinner(f"{name} 사업보고서 분석 중... (약 10~20초)"):
            result = run_analysis(dart, corp_code, name, claude_api_key)

        if "error" in result:
            st.error(result["error"])
        else:
            col_a, col_b = st.columns(2)

            with col_a:
                st.markdown("#### 📌 사업 요약")
                st.write(result.get("summary", "-"))

                st.markdown("#### 🏰 경쟁우위 (해자)")
                st.write(result.get("moat", "-"))

                st.markdown("#### ⚠️ 주요 리스크")
                st.write(result.get("risks", "-"))

            with col_b:
                st.markdown("#### 💰 주주환원")
                st.write(result.get("shareholder", "-"))

                st.markdown("#### 🎯 종합 의견")
                verdict = result.get("verdict", "-")
                st.info(verdict)

            with st.expander("원문 전체 보기"):
                st.text(result.get("raw", ""))
