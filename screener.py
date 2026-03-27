import pandas as pd
from config import SCREENING


def apply_screening(df: pd.DataFrame) -> pd.DataFrame:
    """
    4개 조건을 모두 통과한 종목만 반환.

    입력 df 필요 컬럼:
        operating_margin  (float, 0~1)
        per               (float)
        revenue_growth    (float, 0~1)
        debt_ratio        (float, %)
    """
    crit = SCREENING
    # PER이 NaN이면 해당 조건은 통과 처리 (데이터 없는 경우 제외하지 않음)
    per_mask = df["per"].isna() | ((df["per"] > 0) & (df["per"] <= crit["max_per"]))

    mask = (
        (df["operating_margin"] >= crit["min_operating_margin"])
        & per_mask
        & (df["revenue_growth"] >= crit["min_revenue_growth"])
        & (df["debt_ratio"] > 0)
        & (df["debt_ratio"] <= crit["max_debt_ratio"])
    )
    result = df[mask].copy()
    print(f"[Screener] 전체 {len(df)}개 → 통과 {len(result)}개")
    return result
