# Noting MCP 및 Google Calendar 설정 가이드

## 1. 구현 범위

이번 기능은 다음 두 부분으로 구성된다.

### MCP 서버

- 접속 주소: `/mcp/`
- 전송 방식: Streamable HTTP
- 인증 방식: 기존 Noting JWT를 Bearer 토큰으로 사용
- 계정 격리: 토큰의 사용자 계정을 확인한 뒤 해당 사용자가 소유한 회의와 개인 업무만 조회
- 제공 도구:
  - `search_meetings`: 회의 본문·요약·업무 유사도 검색
  - `ask_meetings`: LangGraph Agentic RAG 질의응답
  - `list_my_tasks`: 본인에게 배정된 업무 조회
  - `get_meeting`: 특정 회의 상세 조회
  - `list_calendar_events`: Google Calendar에 동기화한 향후 일정 조회
  - `sync_calendar_tasks`: 본인 업무의 Google Calendar 동기화

MCP 서버는 외부 AI 클라이언트가 Noting의 기능을 표준 도구처럼 호출할 수 있게 한다. 현재 버전은 시연과 내부 연동을 위해 Noting 로그인 JWT를 직접 받는 리소스 서버 방식이다. 공개 서비스에서 범용 MCP 클라이언트의 자동 로그인을 지원하려면 별도의 OAuth Authorization Server와 동적 클라이언트 등록 구성이 추가로 필요하다.

### Google Calendar 일정 및 알림

- 현재 사용자의 이름으로 배정된 미완료 업무만 동기화
- 회의록이 현재 사용자 소유인지 확인
- `오늘`, `내일`, `모레`, `8월 25일`, `2026년 8월 25일`, `오후 3시`, `15:30` 형식 해석
- 시간 없는 기한은 종일 일정, 시간이 있는 기한은 기본 1시간 일정으로 생성
- Google Calendar 팝업과 이메일 알림을 기본 1일 전에 생성
- 같은 업무는 다시 생성하지 않고 기존 일정을 수정
- 완료·보류·삭제·아카이브된 업무는 연결된 Google 일정을 제거
- Google OAuth 토큰은 암호화하여 데이터베이스에 저장

## 2. Google Cloud 설정

1. Google Cloud Console에서 프로젝트를 선택하거나 생성한다.
2. **Google Calendar API**를 활성화한다.
3. OAuth 동의 화면을 구성한다.
4. 앱이 테스트 상태라면 실제 로그인할 Google 계정을 테스트 사용자로 등록한다.
5. OAuth 클라이언트 유형을 **웹 애플리케이션**으로 생성한다.
6. 승인된 리디렉션 URI에 다음 주소를 정확히 등록한다.

```text
https://서비스도메인/calendar/google/callback
```

공인 IP의 일반 HTTP 주소는 운영용 Google OAuth 리디렉션 URI로 사용하기 어렵다. 실제 서버 연동 전 도메인과 HTTPS를 먼저 구성해야 한다. 로컬 개발은 Google이 허용하는 localhost 리디렉션 URI를 사용한다.

## 3. 서버 환경변수

`.env`에 다음 값을 추가한다. 실제 비밀값은 Git에 커밋하지 않는다.

```dotenv
GOOGLE_CLIENT_ID=발급받은-client-id
GOOGLE_CLIENT_SECRET=발급받은-client-secret
GOOGLE_CALENDAR_REDIRECT_URI=https://서비스도메인/calendar/google/callback
GOOGLE_CALENDAR_TIMEZONE=Asia/Seoul
GOOGLE_CALENDAR_REMINDER_MINUTES=1440

# Fernet 키 문자열 또는 충분히 긴 임의 문자열
# 비워 두면 SECRET_KEY에서 암호화 키를 파생하지만 운영에서는 별도 값을 권장한다.
TOKEN_ENCRYPTION_KEY=운영용-별도-비밀값

MCP_ISSUER_URL=https://서비스도메인
MCP_RESOURCE_SERVER_URL=https://서비스도메인/mcp
```

`TOKEN_ENCRYPTION_KEY`를 바꾸면 기존에 암호화해 저장한 Google 토큰을 복호화할 수 없다. 변경 시 사용자는 Google Calendar를 다시 연결해야 한다.

## 4. 데이터베이스와 배포

```bash
cd ~/noting
git pull --ff-only origin main
uv sync --frozen --no-dev
uv run python scripts/migrate_google_calendar.py
sudo systemctl restart noting
sudo systemctl status noting --no-pager
```

마이그레이션은 다음 테이블을 만든다.

- `google_calendar_connections`: 사용자별 OAuth 연결과 암호화 토큰
- `google_calendar_event_links`: Noting 업무와 Google 일정의 1:1 연결

## 5. 사용자 동작

1. Noting에 로그인한다.
2. 오른쪽 위 Google Calendar 아이콘을 누른다.
3. **Google Calendar 연결**을 누르고 Google 동의를 완료한다.
4. 다시 Noting으로 돌아오면 **지금 동기화**를 누른다.
5. 이후 회의 분석, 업무 상태·기한 변경, 아카이브 처리 때 연결된 계정의 일정을 자동으로 동기화한다.

Google API 장애가 발생해도 회의 분석이나 업무 변경 자체는 실패시키지 않는다. 캘린더 동기화만 로그에 남기고 다음 수동 또는 자동 동기화 때 다시 맞춘다.

## 6. MCP 확인

MCP Inspector 같은 Streamable HTTP 클라이언트에서 다음 값을 사용한다.

```text
URL: https://서비스도메인/mcp/
Authorization: Bearer <Noting 로그인 JWT>
```

현재 Noting JWT의 기본 만료 시간은 60분이다. 만료되면 다시 로그인해 새 토큰을 사용한다. 캘린더 변경 도구인 `sync_calendar_tasks`는 사용자가 동기화를 명시적으로 요청했을 때만 호출한다.

## 7. 점검 명령

```bash
uv run --group dev pytest -q
node --check app/static/app.js
curl -i https://서비스도메인/mcp/
```

인증 없이 MCP 주소를 호출했을 때 `401 Unauthorized`가 반환되는 것이 정상이다.
