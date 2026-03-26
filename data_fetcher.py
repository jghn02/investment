import time
import warnings
import pandas as pd
import FinanceDataReader as fdr
import OpenDartReader
from config import DART_API_KEY, MARKETS

warnings.filterwarnings("ignore")


def get_stock_list() -> pd.DataFrame:
    """코스피 + 코스닥 전체 종목 리스트 반환."""
    frames = []
    for market in MARKETS:
        df = fdr.StockListing(market)[["Code", "Name", "Market"]].copy()
        frames.append(df)
    result = pd.concat(frames, ignore_index=True)
    print(f"[Fetcher] 종목 수집 완료: {len(result)}개")
    return result


def get_dart_corp_codes(dart: OpenDartReader.OpenDartReader) -> pd.DataFrame:
    """DART 기업코드 목록 (종목코드 → corp_code 매핑용)."""
    corp_list = dart.corp_codes
    # stock_code 컬럼만 사용
    corp_list = corp_list[corp_list["stock_code"].notna() & (corp_list["stock_code"] != "")].copy()
    corp_list["stock_code"] = corp_list["stock_code"].str.strip().str.zfill(6)
    return corp_list.set_index("stock_code")


def _parse_amount(val) -> float:
    """DART 재무데이터 금액 파싱 (문자열 → float)."""
    try:
        return float(str(val).replace(",", "").replace(" ", ""))
    except Exception:
        return None


def get_financial_data(dart: OpenDartReader.OpenDartReader, corp_code: str) -> dict:
    """
    DART API로 최근 연간 손익계산서 + 재무상태표 수집.
    반환: {"revenue", "revenue_prev", "operating_income", "total_debt", "total_equity"}
    """
    try:
        # 최근 2년치 연간 재무제표
        df = dart.finstate_all(corp_code, bsns_year=None, reprt_code="11011")  # 사업보고서
        if df is None or df.empty:
            return {}

        # 계정명 기준 필터링 (CFS 연결 우선, 없으면 OFS 별도)
        fs_div_order = ["CFS", "OFS"]
        for fs_div in fs_div_order:
            sub = df[df["fs_div"] == fs_div].copy()
            if not sub.empty:
                break
        else:
            return {}

        def pick(account_name: str, year_col: str):
            row = sub[sub["account_nm"].str.contains(account_name, na=False)]
            if row.empty:
                return None
            val = row.iloc[0].get(year_col)
            return _parse_amount(val)

        # thstrm=당기, frmtrm=전기
        revenue = pick("매출액", "thstrm_amount") or pick("수익(매출액)", "thstrm_amount")
        revenue_prev = pick("매출액", "frmtrm_amount") or pick("수익(매출액)", "frmtrm_amount")
        op_income = pick("영업이익", "thstrm_amount")
        total_debt = pick("부채총계", "thstrm_amount")
        total_equity = pick("자본총계", "thstrm_amount")

        return {
            "revenue": revenue,
            "revenue_prev": revenue_prev,
            "operating_income": op_income,
            "total_debt": total_debt,
            "total_equity": total_equity,
        }
    except Exception as e:
        return {}


def get_per(stock_code: str) -> float:
    """FinanceDataReader로 현재 PER 가져오기."""
    try:
        # FDR 종목 정보에서 PER 시도
        info = fdr.StockListing("KRX")
        row = info[info["Code"] == stock_code]
        if not row.empty and "PER" in row.columns:
            per = row.iloc[0]["PER"]
            if pd.notna(per) and per > 0:
                return float(per)
    except Exception:
        pass
    return None


def build_financials(stock_code: str, fin_data: dict) -> dict:
    """재무 데이터 → 지표 계산."""
    rev = fin_data.get("revenue")
    rev_prev = fin_data.get("revenue_prev")
    op = fin_data.get("operating_income")
    debt = fin_data.get("total_debt")
    equity = fin_data.get("total_equity")

    result = {}

    # 영업이익률
    if rev and op and rev != 0:
        result["operating_margin"] = op / rev

    # 매출 성장률
    if rev and rev_prev and rev_prev != 0:
        result["revenue_growth"] = (rev - rev_prev) / abs(rev_prev)

    # 부채비율
    if debt is not None and equity and equity != 0:
        result["debt_ratio"] = debt / equity * 100

    return result


def collect_all(stock_list: pd.DataFrame, dart: OpenDartReader.OpenDartReader,
                corp_code_map: pd.DataFrame, max_stocks: int = None,
                progress_callback=None) -> pd.DataFrame:
    """
    전체 종목에 대해 재무 데이터 수집 후 DataFrame 반환.
    max_stocks: 테스트용 제한 (None이면 전체)
    progress_callback: (current, total, name) → None (Streamlit progress bar용)
    """
    if max_stocks:
        stock_list = stock_list.head(max_stocks)

    records = []
    total = len(stock_list)

    for i, row in enumerate(stock_list.itertuples(), 1):
        code = str(row.Code).zfill(6)
        name = row.Name
        market = row.Market

        if progress_callback:
            progress_callback(i, total, name)

        # DART corp_code 조회
        if code not in corp_code_map.index:
            continue
        corp_code = corp_code_map.loc[code, "corp_code"]

        # 재무 데이터
        fin_data = get_financial_data(dart, corp_code)
        if not fin_data:
            continue

        metrics = build_financials(code, fin_data)
        if len(metrics) < 3:  # 필수 지표 부족하면 스킵
            continue

        # PER
        per = get_per(code)
        if per is None:
            continue

        record = {
            "code": code,
            "name": name,
            "market": market,
            "per": per,
            **metrics,
        }
        records.append(record)

        time.sleep(0.1)  # DART API rate limit

        if i % 50 == 0:
            print(f"[Fetcher] {i}/{total} 처리 중...")

    df = pd.DataFrame(records)
    print(f"[Fetcher] 재무 데이터 수집 완료: {len(df)}개 유효 종목")
    return df
