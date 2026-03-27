"""
로컬 실행 전용 — 재무 데이터 수집 스크립트
분기 1회 실행 후 GitHub에 push하면 Streamlit 앱에서 즉시 사용 가능.

Usage:
    python3 collect_data.py              # 전체 수집
    python3 collect_data.py --max 200    # 테스트용 200개
    python3 collect_data.py --push       # 수집 후 GitHub 자동 push
"""
import argparse
import datetime
import os
import subprocess
import sys

import pandas as pd

from config import DART_API_KEY
from data_fetcher import (
    FastDart, get_stock_list, get_dart_corp_codes,
    build_per_map, get_financial_data, build_financials, _get_bsns_year
)

OUTPUT_FILE = "financial_data.csv"


def collect(max_stocks=None):
    api_key = DART_API_KEY
    if not api_key:
        api_key = input("DART API 키: ").strip()

    dart = FastDart(api_key)

    print("종목 리스트 수집 중...")
    stock_list = get_stock_list()
    corp_code_map = get_dart_corp_codes(dart)

    print("PER 수집 중 (로컬 환경)...")
    per_map = build_per_map()

    bsns_year = _get_bsns_year()
    print(f"재무 기준 연도: {bsns_year}")

    if max_stocks:
        stock_list = stock_list.head(max_stocks)

    total = len(stock_list)
    records = []

    for i, row in enumerate(stock_list.itertuples(), 1):
        code   = str(row.Code).zfill(6)
        name   = row.Name
        market = row.Market

        if i % 50 == 0 or i == 1:
            print(f"  {i}/{total} — {name}")

        if code not in corp_code_map.index:
            continue
        corp_code = corp_code_map.loc[code, "corp_code"]

        fin_data = get_financial_data(dart, corp_code, bsns_year)
        if not fin_data:
            continue

        metrics = build_financials(fin_data)
        if len(metrics) < 3:
            continue

        records.append({
            "code":   code,
            "name":   name,
            "market": market,
            "per":    per_map.get(code, float("nan")),
            "collected_at": datetime.date.today().isoformat(),
            "bsns_year": bsns_year,
            **metrics,
        })

    df = pd.DataFrame(records)
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUTPUT_FILE} ({len(df)}개 종목)")
    return df


def push_to_github(token: str, today: str):
    """GitHub에 financial_data.csv 자동 push."""
    try:
        remote = f"https://{token}@github.com/jghn02/investment.git"
        subprocess.run(["git", "add", OUTPUT_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"data: financial_data 갱신 ({today})"], check=True)
        subprocess.run(["git", "push", remote, "main"], check=True)
        print("GitHub push 완료")
    except subprocess.CalledProcessError as e:
        print(f"GitHub push 실패: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--push", action="store_true", help="수집 후 GitHub push")
    args = parser.parse_args()

    df = collect(max_stocks=args.max)

    if args.push and not df.empty:
        token = input("GitHub PAT 토큰: ").strip()
        push_to_github(token, datetime.date.today().isoformat())
