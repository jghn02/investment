import os
import time
import datetime
import warnings
import pandas as pd
import FinanceDataReader as fdr
import OpenDartReader
from config import DART_API_KEY, MARKETS

warnings.filterwarnings("ignore")

CORP_CODES_CSV = os.path.join(os.path.dirname(__file__), "corp_codes.csv")


class FastDart(OpenDartReader):
    """
    DART 초기화 시 기업코드를 API로 다운로드하지 않고 로컬 CSV에서 로드.
    Streamlit Cloud 등 해외 서버에서의 타임아웃 방지용.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.corp_codes = pd.read_csv(CORP_CODES_CSV, dtype=str).fillna("")


def _get_bsns_year() -> str:
    """
    사업보고서 기준 연도 결정.
    4월 이전이면 전전년도(확정 보고서 보장), 4월 이후면 전년도 사용.
    """
    today = datetime.date.today()
    return str(today.year - 2 if today.month < 4 else today.year - 1)


def get_stock_list() -> pd.DataFrame:
    """
    코스피 + 코스닥 종목 리스트 반환.
    FDR(KRX API) 실패 시 corp_codes.csv 폴백 사용.
    """
    frames = []
    for market in MARKETS:
        try:
            df = fdr.StockListing(market)[["Code", "Name", "Market"]].copy()
            frames.append(df)
        except Exception:
            pass

    if frames:
        result = pd.concat(frames, ignore_index=True)
        print(f"[Fetcher] FDR 종목 수집 완료: {len(result)}개")
        return result

    # KRX API 다운 시 → DART corp_codes.csv 폴백
    print("[Fetcher] KRX API 불가 → corp_codes.csv 폴백 사용")
    corp = pd.read_csv(CORP_CODES_CSV, dtype=str).fillna("")
    listed = corp[corp["stock_code"].str.len() == 6].copy()
    listed = listed.rename(columns={"stock_code": "Code", "corp_name": "Name"})
    listed["Market"] = "KRX"
    result = listed[["Code", "Name", "Market"]].reset_index(drop=True)
    print(f"[Fetcher] 폴백 종목 수집 완료: {len(result)}개")
    return result


def get_dart_corp_codes(dart) -> pd.DataFrame:
    """DART 기업코드 목록 (종목코드 → corp_code 매핑용)."""
    corp_list = dart.corp_codes.copy()
    corp_list = corp_list[corp_list["stock_code"].notna() & (corp_list["stock_code"] != "")].copy()
    corp_list["stock_code"] = corp_list["stock_code"].str.strip().str.zfill(6)
    return corp_list.set_index("stock_code")


def build_per_map() -> dict:
    """
    FDR에서 코스피/코스닥 PER 딕셔너리 {종목코드: PER} 한 번만 수집.
    KRX API 접근 실패 시 빈 dict 반환 (PER 없이 진행).
    """
    per_map = {}
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            listing = fdr.StockListing(market)
            if "PER" not in listing.columns:
                continue
            for _, row in listing.iterrows():
                code = str(row["Code"]).zfill(6)
                per = row["PER"]
                try:
                    per_f = float(per)
                    if per_f > 0:
                        per_map[code] = per_f
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass
    print(f"[Fetcher] PER 수집: {len(per_map)}개 종목")
    return per_map


def _parse_amount(val) -> float:
    """DART 재무데이터 금액 파싱 (문자열 → float)."""
    try:
        return float(str(val).replace(",", "").replace(" ", ""))
    except Exception:
        return None


def get_financial_data(dart, corp_code: str, bsns_year: str) -> dict:
    """
    DART API로 연간 손익계산서 + 재무상태표 수집.
    CFS(연결) 우선 → 없으면 OFS(별도) 시도.
    반환: {"revenue", "revenue_prev", "operating_income", "total_debt", "total_equity"}
    """
    try:
        sub = None
        for fs_div in ["CFS", "OFS"]:
            df = dart.finstate_all(corp_code, bsns_year=bsns_year,
                                   reprt_code="11011", fs_div=fs_div)
            if df is not None and not df.empty:
                sub = df
                break

        if sub is None:
            return {}

        def pick(account_name: str, year_col: str):
            row = sub[sub["account_nm"].str.contains(account_name, na=False)]
            if row.empty:
                return None
            return _parse_amount(row.iloc[0].get(year_col))

        revenue      = pick("매출액", "thstrm_amount") or pick("수익(매출액)", "thstrm_amount")
        revenue_prev = pick("매출액", "frmtrm_amount") or pick("수익(매출액)", "frmtrm_amount")
        op_income    = pick("영업이익", "thstrm_amount")
        total_debt   = pick("부채총계", "thstrm_amount")
        total_equity = pick("자본총계", "thstrm_amount")

        return {
            "revenue": revenue,
            "revenue_prev": revenue_prev,
            "operating_income": op_income,
            "total_debt": total_debt,
            "total_equity": total_equity,
        }
    except Exception:
        return {}


def build_financials(fin_data: dict) -> dict:
    """재무 데이터 → 지표 계산."""
    rev    = fin_data.get("revenue")
    rev_p  = fin_data.get("revenue_prev")
    op     = fin_data.get("operating_income")
    debt   = fin_data.get("total_debt")
    equity = fin_data.get("total_equity")

    result = {}
    if rev and op and rev != 0:
        result["operating_margin"] = op / rev
    if rev and rev_p and rev_p != 0:
        result["revenue_growth"] = (rev - rev_p) / abs(rev_p)
    if debt is not None and equity and equity != 0:
        result["debt_ratio"] = debt / equity * 100

    return result


def collect_all(stock_list: pd.DataFrame, dart,
                corp_code_map: pd.DataFrame, max_stocks: int = None,
                progress_callback=None) -> pd.DataFrame:
    """
    전체 종목에 대해 재무 데이터 수집 후 DataFrame 반환.
    - PER은 루프 전에 한 번만 수집 (KRX API 실패 시 NaN으로 허용)
    - bsns_year는 확정 보고서가 있는 연도로 자동 결정
    """
    if max_stocks:
        stock_list = stock_list.head(max_stocks)

    bsns_year = _get_bsns_year()
    per_map = build_per_map()
    print(f"[Fetcher] 기준 연도: {bsns_year}, PER 보유: {len(per_map)}개")

    records = []
    total = len(stock_list)

    for i, row in enumerate(stock_list.itertuples(), 1):
        code   = str(row.Code).zfill(6)
        name   = row.Name
        market = row.Market

        if progress_callback:
            progress_callback(i, total, name)

        if code not in corp_code_map.index:
            continue
        corp_code = corp_code_map.loc[code, "corp_code"]

        fin_data = get_financial_data(dart, corp_code, bsns_year)
        if not fin_data:
            continue

        metrics = build_financials(fin_data)
        if len(metrics) < 3:
            continue

        # PER: 없으면 NaN (스크리너가 처리)
        per = per_map.get(code, float("nan"))

        records.append({
            "code":   code,
            "name":   name,
            "market": market,
            "per":    per,
            **metrics,
        })

        time.sleep(0.1)

        if i % 50 == 0:
            print(f"[Fetcher] {i}/{total} 처리 중...")

    df = pd.DataFrame(records)
    print(f"[Fetcher] 재무 데이터 수집 완료: {len(df)}개 유효 종목")
    return df
