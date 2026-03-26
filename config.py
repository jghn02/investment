import os

# DART API 키 설정
# 1. https://opendart.fss.or.kr 에서 발급 (이메일 인증 후 즉시 발급)
# 2. 아래 빈 문자열에 직접 입력하거나,
#    환경변수 DART_API_KEY 또는 Streamlit Cloud Secrets에 설정
DART_API_KEY = os.environ.get("DART_API_KEY", "940530315aaac0d5b35cce1486cb50e09f89d42b")

# 스크리닝 기준값
SCREENING = {
    "min_operating_margin": 0.10,   # 영업이익률 10% 이상
    "max_per": 20,                   # PER 20배 이하
    "min_revenue_growth": 0.10,      # 매출 성장률 10% 이상
    "max_debt_ratio": 200,           # 부채비율 200% 이하
}

# 스코어링 가중치 (합계 = 1.0)
WEIGHTS = {
    "operating_margin": 0.30,
    "per": 0.25,
    "revenue_growth": 0.25,
    "debt_ratio": 0.20,
}

# 수집 대상 시장
MARKETS = ["KOSPI", "KOSDAQ"]

# 결과 저장 경로
OUTPUT_DIR = "output"
