"""
한국 주식 추천 시스템 — 터미널 실행 진입점
Usage: python3 main.py [--max N]
"""
import argparse
import os
import datetime
import pandas as pd
import OpenDartReader

from config import DART_API_KEY, OUTPUT_DIR
from data_fetcher import get_stock_list, get_dart_corp_codes, collect_all
from screener import apply_screening
from scorer import calculate_score


DISPLAY_COLS = [
    "rank", "name", "market", "score",
    "operating_margin", "per", "revenue_growth", "debt_ratio",
]


def format_display(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.insert(0, "rank", range(1, len(out) + 1))
    out["operating_margin"] = (out["operating_margin"] * 100).round(1).astype(str) + "%"
    out["revenue_growth"] = (out["revenue_growth"] * 100).round(1).astype(str) + "%"
    out["debt_ratio"] = out["debt_ratio"].round(1).astype(str) + "%"
    out["per"] = out["per"].round(1)
    return out[DISPLAY_COLS]


def save_excel(df: pd.DataFrame) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str = datetime.date.today().strftime("%Y%m%d")
    path = os.path.join(OUTPUT_DIR, f"추천종목_{date_str}.xlsx")
    df.to_excel(path, index=False)
    return path


def main():
    parser = argparse.ArgumentParser(description="한국 주식 스크리닝 & 추천")
    parser.add_argument("--max", type=int, default=None,
                        help="테스트용: 최대 종목 수 제한 (예: --max 100)")
    args = parser.parse_args()

    # API 키 확인
    api_key = DART_API_KEY
    if not api_key:
        api_key = input("DART API 키를 입력하세요 (opendart.fss.or.kr): ").strip()
    if not api_key:
        print("ERROR: DART API 키가 없으면 실행할 수 없습니다.")
        return

    dart = OpenDartReader.OpenDartReader(api_key)

    print("=" * 60)
    print("  한국 주식 추천 시스템")
    print("=" * 60)

    # 1. 종목 리스트
    print("\n[1/4] 종목 리스트 수집 중...")
    stock_list = get_stock_list()

    # 2. DART 기업코드 매핑
    print("[2/4] DART 기업코드 매핑 중...")
    corp_code_map = get_dart_corp_codes(dart)

    # 3. 재무 데이터 수집
    print(f"[3/4] 재무 데이터 수집 중... (총 {len(stock_list)}개 종목, 시간 소요)")
    df_raw = collect_all(stock_list, dart, corp_code_map, max_stocks=args.max)

    if df_raw.empty:
        print("수집된 데이터가 없습니다. DART API 키를 확인하세요.")
        return

    # 4. 스크리닝
    print("[4/4] 스크리닝 & 스코어링 중...")
    df_screened = apply_screening(df_raw)

    if df_screened.empty:
        print("스크리닝 통과 종목이 없습니다. 기준값을 완화해보세요.")
        return

    df_scored = calculate_score(df_screened)

    # 결과 출력
    top20 = df_scored.head(20)
    display = format_display(top20)

    print("\n" + "=" * 60)
    print(f"  상위 20개 추천 종목 (스크리닝 통과: {len(df_scored)}개)")
    print("=" * 60)
    print(display.to_string(index=False))

    # Excel 저장
    path = save_excel(df_scored)
    print(f"\n전체 결과 저장: {path}")


if __name__ == "__main__":
    main()
