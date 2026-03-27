"""
한국 주식 추천 시스템 — Streamlit 웹앱
"""
import os
import time
import datetime
import io
import pandas as pd
import streamlit as st
from data_fetcher import get_stock_list, get_dart_corp_codes, collect_all, FastDart
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
st.sidebar.markdown("**기업코드 관리**")

# corp_codes.csv 마지막 수정일 표시
_csv_path = os.path.join(os.path.dirname(__file__), "corp_codes.csv")
if os.path.exists(_csv_path):
    _mtime = os.path.getmtime(_csv_path)
    _mdate = datetime.datetime.fromtimestamp(_mtime).strftime("%Y-%m-%d")
    st.sidebar.caption(f"기업코드 기준일: {_mdate}")
else:
    st.sidebar.caption("기업코드 파일 없음")

if st.sidebar.button("🔄 기업코드 갱신", help="DART에서 최신 기업코드 다운로드 후 GitHub에 자동 push"):
    if not dart_api_key:
        st.sidebar.error("DART API 키를 먼저 입력하세요.")
    else:
        github_token = load_secret("GITHUB_TOKEN")
        with st.sidebar.spinner("갱신 중..."):
            try:
                import base64, requests as _req
                import OpenDartReader as _odr

                # 1. DART에서 최신 기업코드 수집
                _dart_tmp = _odr(dart_api_key)
                _df = _dart_tmp.corp_codes
                _df.to_csv(_csv_path, index=False)

                # 2. GitHub에 push (토큰이 있을 때만)
                if github_token:
                    _api_url = "https://api.github.com/repos/jghn02/investment/contents/corp_codes.csv"
                    _headers = {"Authorization": f"token {github_token}"}
                    _sha = _req.get(_api_url, headers=_headers).json().get("sha", "")
                    with open(_csv_path, "rb") as f:
                        _content = base64.b64encode(f.read()).decode()
                    _req.put(_api_url, headers=_headers, json={
                        "message": f"chore: corp_codes 갱신 ({datetime.date.today()})",
                        "content": _content,
                        "sha": _sha,
                    })
                    st.sidebar.success(f"완료 + GitHub push: {len(_df):,}개 기업 ({datetime.date.today()})")
                else:
                    st.sidebar.success(f"완료 (로컬만): {len(_df):,}개 기업 — GitHub push는 GITHUB_TOKEN 설정 필요")
            except Exception as e:
                st.sidebar.error(f"실패: {e}")

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

        dart = FastDart(dart_api_key)
        st.session_state.dart = dart

        # ── 단계 인디케이터 ──
        STEPS = ["① 종목 수집", "② 재무 수집", "③ 스크리닝", "④ 스코어링"]
        step_placeholder = st.empty()

        def render_steps(active: int):
            cols = step_placeholder.columns(4)
            for i, (col, label) in enumerate(zip(cols, STEPS)):
                if i < active:
                    col.success(label)
                elif i == active:
                    col.info(f"🔄 {label}")
                else:
                    col.empty()

        # Step 1: 종목 수집
        render_steps(0)
        with st.spinner("종목 리스트 수집 중..."):
            stock_list = get_stock_list()
            corp_code_map = get_dart_corp_codes(dart)
            st.session_state.corp_code_map = corp_code_map
        total_count = min(max_stocks, len(stock_list)) if max_stocks else len(stock_list)

        # Step 2: 재무 수집
        render_steps(1)
        progress_bar = st.progress(0)
        stat_cols = st.columns(3)
        pct_box = stat_cols[0].empty()
        count_box = stat_cols[1].empty()
        time_box = stat_cols[2].empty()
        stock_name_box = st.empty()
        start_time = time.time()

        def progress_callback(current, total, name):
            pct = int(current / total * 100)
            elapsed = time.time() - start_time
            rate = current / elapsed if elapsed > 0 else 1
            remaining = int((total - current) / rate) if rate > 0 else 0
            mins, secs = divmod(remaining, 60)

            progress_bar.progress(pct)
            pct_box.metric("진행률", f"{pct}%")
            count_box.metric("처리", f"{current:,} / {total:,}")
            time_box.metric("남은 시간", f"{mins}분 {secs}초" if mins else f"{secs}초")
            stock_name_box.caption(f"🔍 현재 종목: **{name}**")

        df_raw = collect_all(stock_list, dart, corp_code_map,
                             max_stocks=max_stocks,
                             progress_callback=progress_callback)

        # 진행 UI 정리
        progress_bar.empty()
        pct_box.empty(); count_box.empty(); time_box.empty(); stock_name_box.empty()

        if df_raw.empty:
            st.error("재무 데이터 수집 실패. DART API 키를 확인하세요.")
            st.stop()

        # Step 3: 스크리닝
        render_steps(2)
        df_screened = apply_screening(df_raw)
        if df_screened.empty:
            st.warning("스크리닝 통과 종목 없음. 기준값을 완화해보세요.")
            st.stop()

        # Step 4: 스코어링
        render_steps(3)
        st.session_state.df_scored = calculate_score(df_screened)
        render_steps(4)  # 전체 완료

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
