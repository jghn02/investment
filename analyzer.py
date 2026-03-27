"""
DART 사업보고서 핵심 섹션 추출 + Claude API 분석
"""
import re
import requests
from bs4 import BeautifulSoup
import anthropic
import OpenDartReader

# 추출 대상 섹션 (DART 서브문서 제목 키워드)
TARGET_SECTIONS = {
    "사업내용": ["사업의 내용"],
    "리스크": ["사업의 위험", "위험관리", "불확실성"],
    "경영진": ["임원의 현황"],
    "배당": ["배당에 관한 사항"],
    "계열사": ["계열회사 현황"],
}

MAX_CHARS_PER_SECTION = 2000  # 섹션당 최대 문자 수


def _clean_html(html_bytes: bytes) -> str:
    """HTML → 깔끔한 텍스트 변환."""
    try:
        soup = BeautifulSoup(html_bytes, "html.parser")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # 연속 빈줄 제거
        lines = [l for l in text.splitlines() if l.strip()]
        return "\n".join(lines)
    except Exception:
        return ""


def get_latest_annual_report(dart: FastDart, corp_code: str) -> str | None:
    """최근 사업보고서 rcp_no 반환."""
    try:
        reports = dart.report_list(corp_code, bgn_de="20220101", pblntf_ty="A")
        if reports is None or reports.empty:
            return None
        annual = reports[reports["report_nm"].str.contains("사업보고서", na=False)]
        if annual.empty:
            return None
        return annual.iloc[0]["rcp_no"]
    except Exception:
        return None


def extract_sections(dart: FastDart, rcp_no: str) -> dict:
    """
    서브문서 목록에서 TARGET_SECTIONS에 해당하는 섹션 텍스트 추출.
    반환: {"사업내용": "...", "리스크": "...", ...}
    """
    try:
        sub_docs = dart.sub_docs(rcp_no)
        if sub_docs is None or sub_docs.empty:
            return {}
    except Exception:
        return {}

    results = {}

    for category, keywords in TARGET_SECTIONS.items():
        for _, row in sub_docs.iterrows():
            title = str(row.get("title", ""))
            if any(kw in title for kw in keywords):
                url = row.get("url", "")
                if not url:
                    continue
                try:
                    resp = requests.get(url, timeout=10)
                    text = _clean_html(resp.content)
                    results[category] = text[:MAX_CHARS_PER_SECTION]
                    break
                except Exception:
                    continue

    return results


def analyze_with_claude(
    company_name: str,
    sections: dict,
    api_key: str,
) -> dict:
    """
    추출된 섹션 텍스트를 Claude Haiku에 전달 → 구조화된 분석 반환.
    반환: {"summary": "...", "moat": "...", "risks": "...", "shareholder": "...", "verdict": "..."}
    """
    client = anthropic.Anthropic(api_key=api_key)

    section_text = "\n\n".join(
        f"[{cat}]\n{text}" for cat, text in sections.items() if text
    )

    if not section_text:
        return {"error": "추출된 섹션 데이터 없음"}

    prompt = f"""아래는 '{company_name}'의 사업보고서 핵심 섹션입니다.
PM·투자자 관점에서 간결하게 분석해주세요.

{section_text}

다음 항목을 각각 3~5문장으로 한국어로 작성하세요:

1. 사업 요약: 주력 사업과 매출 구조
2. 경쟁우위(해자): 진입장벽, 시장점유율, 차별화 요소
3. 주요 리스크: 매출 집중도, 규제, 경쟁 위협
4. 주주환원: 배당 이력, 자사주 매입, 경영진 보수 수준
5. 종합 의견: 투자 매력도 한 줄 요약

각 항목은 "항목명: 내용" 형식으로 출력하세요."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text

        # 항목별 파싱
        result = {}
        patterns = {
            "사업 요약": "summary",
            "경쟁우위": "moat",
            "주요 리스크": "risks",
            "주주환원": "shareholder",
            "종합 의견": "verdict",
        }
        for label, key in patterns.items():
            match = re.search(rf"{label}[^\n]*:\s*(.+?)(?=\n\d\.|$)", raw, re.DOTALL)
            result[key] = match.group(1).strip() if match else ""

        result["raw"] = raw
        return result

    except Exception as e:
        return {"error": str(e)}


def run_analysis(
    dart: FastDart,
    corp_code: str,
    company_name: str,
    claude_api_key: str,
) -> dict:
    """메인 분석 파이프라인."""
    rcp_no = get_latest_annual_report(dart, corp_code)
    if not rcp_no:
        return {"error": f"{company_name}: 사업보고서를 찾을 수 없습니다."}

    sections = extract_sections(dart, rcp_no)
    if not sections:
        return {"error": f"{company_name}: 섹션 추출 실패 (DART 접근 오류)"}

    return analyze_with_claude(company_name, sections, claude_api_key)
