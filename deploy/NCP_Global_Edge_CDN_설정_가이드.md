# Noting Naver Cloud Global Edge CDN 설정 가이드

## 1. 적용 범위

Noting의 HTML, API, 로그인, MCP, Google OAuth는 계속 `https://noting.kro.kr`에서 처리한다. CDN에는 다음 두 정적 파일만 캐시한다.

- `/ui/styles.css`
- `/ui/app.js`

회의록, 사용자 정보, 토큰, API 응답은 CDN 캐시 대상이 아니다.

## 2. Global Edge 생성

Naver Cloud Platform 콘솔에서 **Services → Content Delivery → Global Edge**로 이동한다.

1. 프로필이 없으면 Noting용 프로필을 하나 만든다.
2. **Edge 생성 → Self Integration**을 선택한다.
3. 배포 설정:
   - Edge 이름: `noting-static`
   - Service Protocol: `HTTPS`
   - Service Region: `Korea`
   - Service Domain: **NAVER Cloud Platform 도메인 사용 → 자동 생성**
4. 원본 설정:
   - Origin type: `외부 오리진`
   - Origin domain: `noting.kro.kr`
   - Origin protocol: `HTTPS`
   - Origin port: `443`
   - Forward Host Header: `Custom`
   - Custom Host Header: `noting.kro.kr`
   - Origin path: 비워 둔다.

발급된 주소는 `임의값.edge.naverncp.com` 형태이며 별도 도메인 구매가 필요 없다.

## 3. 캐시 규칙

캐시 키에서 Query String을 포함하도록 설정한다. Noting은 파일 내용 해시를 `?v=...`로 붙이므로 새 배포 시 새 캐시 객체가 생성된다.

허용 캐시 규칙:

| 조건 | 동작 |
|---|---|
| Path가 `/ui/styles.css` | Cache |
| Path가 `/ui/app.js` | Cache |
| 그 외 모든 경로 | Bypass cache |

권장 설정:

- Browser cache: Origin의 `Cache-Control` 헤더 사용
- Edge TTL: Origin 헤더 우선, 최대 30일
- Query String: 캐시 키에 포함
- Serve stale: 원본 장애 시 사용 가능
- 압축: gzip 또는 Brotli 사용 가능

`/`, `/ui/`, `/auth/*`, `/users/*`, `/transcripts/*`, `/calendar/*`, `/mcp`, `/authorize`, `/token`, `/register`, `/revoke`, `/.well-known/*`는 캐시하면 안 된다.

## 4. 서버 환경변수

Global Edge 배포가 완료되면 발급된 실제 주소를 서버 `.env`에 넣는다.

```dotenv
STATIC_ASSET_BASE_URL=https://발급주소.edge.naverncp.com/ui
STATIC_ASSET_VERSION=
```

`STATIC_ASSET_VERSION`을 비워 두면 애플리케이션이 `styles.css`와 `app.js` 내용으로 버전을 자동 계산한다.

## 5. 서버 반영

```bash
cd /root/noting
git pull --ff-only origin main
uv sync --frozen --no-dev
uv run python -m scripts.migrate_mcp_oauth
sudo systemctl restart noting
sudo systemctl status noting --no-pager
```

## 6. 검증

HTML이 CDN 주소를 사용하고 있는지 확인한다.

```bash
curl -s https://noting.kro.kr/ui/ | grep edge.naverncp.com
```

CDN 정적 파일 응답을 확인한다.

```bash
curl -I "https://발급주소.edge.naverncp.com/ui/styles.css?v=test"
curl -I "https://발급주소.edge.naverncp.com/ui/app.js?v=test"
```

다음을 확인한다.

- HTTP 200
- `Content-Type: text/css` 또는 JavaScript MIME type
- `Cache-Control` 존재
- Global Edge의 cache hit 헤더 또는 콘솔 통계에서 HIT 증가

MCP 검색 문서도 CDN이 아닌 원본에서 응답해야 한다.

```bash
curl -s https://noting.kro.kr/.well-known/oauth-authorization-server
curl -s https://noting.kro.kr/.well-known/oauth-protected-resource/mcp
```

## 7. 롤백

CDN 장애 시 서버 `.env`에서 아래 값을 비우고 애플리케이션만 재시작한다.

```dotenv
STATIC_ASSET_BASE_URL=
```

```bash
sudo systemctl restart noting
```

HTML은 즉시 기존 `/ui/styles.css`, `/ui/app.js`를 사용한다. 회의 데이터와 DB에는 영향이 없다.
