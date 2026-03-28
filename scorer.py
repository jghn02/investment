import pandas as pd
import numpy as np
from config import WEIGHTS


def _normalize(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """윈저화(1~99%) 후 min-max 정규화 → 0~100점. 이상값 왜곡 방지."""
    s = series.clip(series.quantile(0.01), series.quantile(0.99))
    s_min, s_max = s.min(), s.max()
    if s_max == s_min:
        return pd.Series(50.0, index=series.index)
    norm = (s - s_min) / (s_max - s_min) * 100
    return norm if higher_is_better else 100 - norm


def calculate_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    각 지표를 0~100점으로 정규화 후 가중합 → 'score' 컬럼 추가.

    PER·부채비율은 낮을수록 좋음 (역방향 정규화).
    영업이익률·매출성장률은 높을수록 좋음.
    """
    df = df.copy()

    df["score_operating_margin"] = _normalize(df["operating_margin"], higher_is_better=True)
    # PER NaN → 중앙값으로 대체 후 정규화 (데이터 없는 종목 제외하지 않음)
    per_filled = df["per"].fillna(df["per"].median())
    df["score_per"] = _normalize(per_filled, higher_is_better=False)
    df["score_revenue_growth"] = _normalize(df["revenue_growth"], higher_is_better=True)
    df["score_debt_ratio"] = _normalize(df["debt_ratio"], higher_is_better=False)

    w = WEIGHTS
    df["score"] = (
        df["score_operating_margin"] * w["operating_margin"]
        + df["score_per"] * w["per"]
        + df["score_revenue_growth"] * w["revenue_growth"]
        + df["score_debt_ratio"] * w["debt_ratio"]
    ).round(2)

    return df.sort_values("score", ascending=False).reset_index(drop=True)
