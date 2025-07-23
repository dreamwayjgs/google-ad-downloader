# 🚧 현재 BETA 버전입니다

Google Ads 데이터를 간편하게 다운로드할 수 있는 CLI 도구입니다.  
인터랙티브한 방식으로 고객 ID, 캠페인 ID를 선택하고 원하는 리포트를 엑셀 파일로 저장할 수 있습니다.

---

## 📦 주요 기능

- `config.ini`와 `google-ads.yaml` 기반 인증 구성
- `customer_ids`와 연결된 **활성 캠페인 목록 자동 조회**
- 캠페인 선택 후 아래 보고서 중 하나를 선택하여 다운로드:
  - ✅ **YouTube 게재지면 보고서**
  - ✅ **성별/연령별 잠재고객 성과 보고서**
- 다운로드된 결과는 자동으로 `res/output/` 디렉토리에 엑셀로 저장됩니다.
- 실행 종료 시 에러 메시지와 결과 경로를 명확히 출력

---

## 🔧 준비 사항

1. `config.ini` 생성  
   → 예시 파일: `config.ini.sample`

2. `google-ads.yaml` 생성  
   → 생성 방법은 공식 문서 또는 `python -m google.ads.googleads.auth` 참고

---

## 🛠️ 실행 방법

### 개발자 - CLI 모드 실행

```bash
poetry run python -m google_ads_downloader.main
```

### Release

현재 윈도우용만 지원합니다.
