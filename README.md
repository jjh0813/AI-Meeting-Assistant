# Noting

회의 음성을 사용자별 업무 데이터로 전환하는 AI 회의록 관리 서비스입니다. 음성 인식 결과를 사람이 검토한 뒤 요약, 일정 및 요청사항 추출, 회의록 기반 질의응답, 보고서 생성을 하나의 웹 흐름으로 제공합니다.

Noting은 회계·경영·영업 부서가 하나의 AI 인프라를 공유하되, 회의록·업무·RAG 검색 범위는 로그인 계정 단위로 분리합니다. LLM과 다른 사용자에게는 마스킹된 텍스트만 제공하고, 본인 확인된 표시 이름만 해당 사용자 화면에서 제한적으로 복원합니다.

## 주요 기능

- 브라우저 녹음 및 음성 파일 업로드
- CLOVA Speech 기반 한국어 STT
- 이름·전화번호 마스킹 및 원문 분리 저장
- 회의록 저장·수정 후 별도 버튼 없이 자동 분석
- Gemma 기반 자동 회의 제목, 요약과 할 일·담당자·기한·요청사항 추출
- 날짜별 회의 목록과 회의 상세 화면, 사용자 제목 수정
- PostgreSQL·pgvector 기반 계정별 RAG 검색
- 회의록 근거 기반 Q&A와 근거 부족·범위 밖 질문 차단
- LangGraph 기반 Agentic RAG 의도 분류·검색기 선택·질문 재작성·답변 검증
- MCP Streamable HTTP 서버를 통한 회의 검색·질의응답·개인 업무 도구 제공
- 유사 업무 탐지 및 일정 변경 후보 확인
- 업무 상태 관리와 캘린더형 대시보드
- 본인 담당 업무의 Google Calendar 자동 동기화와 하루 전 알림
- 텍스트 및 PDF 보고서 생성
- 부서 관리자 기반 가입 승인과 계정 소유권 보호

## 시스템 구성

```mermaid
flowchart LR
    U["브라우저 UI"] --> REST["FastAPI REST API"]
    MC["MCP 클라이언트"] --> MCP["FastMCP / Streamable HTTP"]
    REST --> AUTH["인증·승인·계정 소유권"]
    MCP --> AUTH
    AUTH --> SVC["공통 서비스 계층"]
    SVC --> STT["CLOVA Speech"]
    SVC --> MASK["개인정보 마스킹"]
    MASK --> DB[("PostgreSQL + pgvector")]
    SVC --> EMB["Ollama / nomic-embed-text"]
    SVC --> LLM["Ollama / Gemma"]
    DB --> RET["계정 필터 + 하이브리드 검색"]
    EMB --> RET
    RET --> AGENT["LangGraph Agentic RAG"]
    AGENT --> LLM
    LLM --> SVC
    SVC --> GCAL["Google Calendar API"]
    SVC --> REPORT["텍스트·PDF 보고서"]
```

### 데이터 처리 흐름

1. 사용자가 브라우저에서 녹음하거나 음성 파일을 업로드합니다.
2. FastAPI가 CLOVA Speech를 호출해 한국어 텍스트를 생성합니다.
3. 이름과 전화번호를 마스킹하고, 마스킹 본문과 개인정보 원문을 분리 저장합니다.
4. 저장 직후 Gemma가 회의 제목, 요약과 업무 항목을 구조화된 JSON으로 자동 추출합니다.
5. 사용자가 마스킹된 회의록을 수정하면 기존 분석을 무효화하고 자동으로 다시 분석합니다.
6. 회의록 청크·요약·업무 항목을 임베딩해 pgvector에 저장합니다.
7. 질문 시 현재 로그인 계정이 소유한 데이터만 검색하고, 벡터 및 어휘 점수를 결합해 근거를 재정렬합니다.
8. LangGraph가 근거 점수를 평가하고 필요하면 질문을 한 번 재작성한 뒤 다시 검색합니다.
9. 충분한 근거가 있을 때만 Gemma가 답변하며, 결과에는 근거 문서, 차단 상태와 노드별 실행 과정이 함께 반환됩니다.
10. 본인에게 배정된 업무에 해석 가능한 기한이 있고 Google Calendar가 연결돼 있으면 분석 완료 후 일정과 하루 전 알림을 동기화합니다.

회의록이 수정되면 이전 요약, 업무 항목 및 검색 청크를 제거한 뒤 자동으로 다시 분석합니다. 사용자가 직접 수정한 회의 제목은 재분석해도 유지됩니다.

Google Calendar 자동 등록은 발언 순간의 실시간 등록이 아닙니다. 회의록 저장과 분석이 완료되어 담당자·업무·기한이 구조화된 후 실행됩니다. `오늘`, `내일`, `모레`, `8월 25일`, `2026년 8월 25일`, `오후 3시`, `15:30` 형식을 해석하며, `조만간`, `가능한 빨리`처럼 날짜가 확정되지 않은 표현은 Noting 업무에는 남지만 Google 일정으로는 만들지 않습니다.

## 기술 스택

| 영역 | 기술 | 사용 목적 |
|---|---|---|
| Backend | Python 3.12, FastAPI | API, 인증, 권한, 처리 파이프라인 |
| Database | PostgreSQL 16, SQLAlchemy | 사용자·회의록·PII·업무 데이터 저장 |
| Vector search | pgvector | 요약·청크·업무 임베딩 검색 |
| LLM runtime | Ollama | 로컬 생성 모델과 임베딩 모델 실행 |
| Generation model | Gemma | 요약, 정보 추출, 근거 기반 답변 |
| Embedding model | nomic-embed-text | 회의록 및 질문 벡터화 |
| Speech recognition | CLOVA Speech | 한국어 음성 인식 |
| Authentication | JWT, Argon2 | Bearer 인증과 비밀번호 해싱 |
| Agent workflow | LangGraph | RAG 상태·노드·조건 분기와 실행 trace |
| Tool protocol | MCP Python SDK, FastMCP | 외부 AI 클라이언트용 표준 도구 서버 |
| Calendar | Google Calendar API, OAuth 2.0 | 개인 업무 일정과 하루 전 알림 동기화 |
| Token protection | Fernet | Google OAuth 토큰 암호화 저장 |
| Reporting | ReportLab | PDF 회의 보고서 생성 |
| Package management | uv | 의존성 및 가상환경 관리 |

LangGraph는 회의 Q&A의 Agentic RAG 흐름에만 사용합니다. 인증·권한·분석·저장 로직은 기존 FastAPI 서비스 계층에 유지해 에이전트가 사용자 범위 밖의 데이터나 임의 도구에 접근하지 못하게 제한합니다.

## 보안 및 권한 모델

### 사용자 상태

- 신규 사용자는 `대기` 상태로 등록됩니다.
- 같은 부서 관리자가 승인해야 서비스 기능을 사용할 수 있습니다.
- 승인 또는 거절 작업은 관리자 API에서 처리합니다.

### 데이터 접근

- 회의록, 검색 청크, 업무 항목은 요청 사용자의 `owner_user_id` 조건으로 조회합니다.
- 같은 부서 사용자라도 다른 계정이 저장한 회의 데이터에는 접근할 수 없습니다.
- 일반 화면에서는 현재 사용자 본인 이름만 복원하고 다른 이름과 전화번호는 계속 마스킹합니다.
- LLM과 임베딩 모델에는 번호가 붙은 내부 마스킹 토큰을 사용하며, RAG 답변 시 서버가 본인 이름만 선택적으로 복원합니다.
- MCP 도구도 전달된 Noting JWT의 사용자를 다시 조회한 후 동일한 계정 소유권 조건을 적용합니다.
- Google OAuth 연결과 일정 연결 정보는 사용자별로 분리하고 액세스·갱신 토큰은 암호화해 저장합니다.

현재 계정 격리는 애플리케이션 쿼리 계층에서 수행합니다. 운영 환경에서는 PostgreSQL Row-Level Security, 감사 로그, 비밀 관리 시스템을 추가하는 것을 권장합니다.

## RAG 검색 구조

검색은 단일 벡터 유사도에만 의존하지 않으며 LangGraph 상태 그래프로 실행됩니다.

1. `scope_guard`가 회의·업무 범위를 벗어난 질문을 검색 전에 차단합니다.
2. `route_intent`가 질문을 개인 업무, 업무, 일정, 결정, 미결, 일반 회의 유형으로 분류합니다.
3. `select_retriever`가 회의 본문, 요약, 실행 항목 중 필요한 DB 검색기만 선택합니다.
4. `retrieve`가 pgvector에서 최종 반환 개수보다 넓은 후보군을 조회합니다.
5. `grade_evidence`가 벡터 유사도 65%와 어휘 유사도 35%의 결합 점수로 근거를 평가합니다.
6. 근거가 부족하면 `rewrite_query`가 원래 의도를 유지한 검색 질문을 한 번 만들고 재검색합니다.
7. 두 번의 검색에서도 근거가 부족하면 LLM 답변 생성 전에 차단합니다.
8. `generate_answer`는 검증된 근거만 사용하고 `verify_answer`가 근거 부족 표현을 최종 검사합니다.

검색은 최초 1회와 재작성 후 1회를 합쳐 최대 2회만 수행되므로 그래프가 무한 반복되지 않습니다. 각 노드의 상태와 설명은 `trace`로 반환되어 프론트의 `Agentic RAG 실행 과정`에서 확인할 수 있습니다.

질의응답 API는 다음 상태를 함께 반환합니다.

- `grounded`: 답변이 검색 근거를 기반으로 생성됐는지 여부
- `blocked`: 질문 또는 근거 부족으로 답변이 차단됐는지 여부
- `blocked_reason`: `out_of_scope`, `low_similarity`, `insufficient_context` 등 차단 사유
- `sources`: 답변 생성에 사용한 현재 계정 소유 회의록 근거
- `intent`, `selected_source_types`: 분류된 의도와 실제 선택한 검색기
- `retrieval_attempts`, `rewritten_question`: 검색 횟수와 질문 보정 결과
- `verification`: 최종 답변 검증 상태
- `trace`: LangGraph 노드별 실행 상태와 사용자용 설명

## MCP 서버

FastAPI 애플리케이션은 `/mcp/`에 stateless Streamable HTTP MCP 서버를 함께 제공합니다. MCP 도구는 별도 데이터 접근 우회 경로를 만들지 않고 기존 서비스와 사용자 소유권 필터를 재사용합니다.

| 도구 | 기능 |
|---|---|
| `search_meetings` | 현재 계정의 회의 본문·요약·업무에서 관련 근거 검색 |
| `ask_meetings` | 현재 계정 근거만 사용하는 LangGraph Agentic RAG 답변 |
| `list_my_tasks` | 현재 사용자에게 배정된 개인 업무 조회 |
| `get_meeting` | 현재 계정이 소유한 특정 회의 상세 조회 |
| `list_calendar_events` | Google Calendar에 동기화한 향후 Noting 일정 조회 |
| `sync_calendar_tasks` | 본인 업무를 Google Calendar에 생성·수정·삭제 동기화 |

현재 MCP 인증은 Noting 로그인에서 발급한 JWT를 Bearer 토큰으로 전달하는 내부 연동 방식입니다.

```text
MCP URL: https://서비스도메인/mcp/
Authorization: Bearer <Noting JWT>
```

JWT 기본 만료 시간은 60분입니다. 범용 MCP 클라이언트에서 로그인과 토큰 발급까지 자동화하려면 향후 별도 OAuth Authorization Server와 동적 클라이언트 등록 구성이 필요합니다.

## Google Calendar 일정 및 알림

사용자가 상단 Google Calendar 버튼에서 OAuth 연결을 완료하면 다음 규칙으로 동작합니다.

1. OAuth 연결 시 `Noting - 표시 이름 (아이디)` 형식의 전용 Google 보조 캘린더를 만듭니다.
2. 전용 캘린더 ID와 Google의 고정 사용자 식별자(`sub`)를 Noting 사용자별로 저장합니다.
3. 현재 계정 소유 회의의 미완료·비아카이브 업무를 조회합니다.
4. PII 토큰을 현재 사용자 이름에 대해서만 복원한 뒤 담당자가 본인인지 검사합니다.
5. 기한을 날짜 또는 날짜·시간으로 해석합니다.
6. 시간 없는 기한은 종일 일정, 시간이 있는 기한은 기본 1시간 일정으로 생성합니다.
7. 팝업과 이메일 알림을 기본 1일 전인 1,440분 전에 설정합니다.
8. 동일 업무는 `google_calendar_event_links`로 식별해 중복 생성하지 않고 수정합니다.
9. 업무 완료·대체·삭제·아카이브 시 연결된 Google 일정을 제거합니다.

동일한 Google 계정을 여러 Noting 계정에서 선택하더라도 각 Noting 계정은 서로 다른 보조 캘린더를 사용합니다. Noting에서 로그아웃하거나 Google 연결을 해제하면 현재 Noting 계정의 OAuth 토큰을 제거해 다음 연결에서 Google 계정 선택 화면을 다시 거치게 합니다. 전용 캘린더 ID와 일정 연결 정보는 보존하므로 같은 Google 계정으로 다시 승인했을 때 기존 전용 캘린더를 재사용합니다. 같은 Google 계정을 사용하는 다른 활성 연결이 있으면 해당 연결의 토큰까지 무효화하지 않습니다. 이전 버전에서 `primary` 캘린더에 연결된 사용자는 화면의 `전용 캘린더 설정` 버튼으로 OAuth 권한을 다시 승인해야 합니다.

회의 분석, 업무 상태 변경, 일정 변경 확정과 아카이브 처리 후에는 자동 동기화를 시도합니다. Google API 장애가 발생해도 핵심 회의 저장이나 업무 변경은 롤백하지 않으며, 캘린더 동기화 실패만 로그로 남겨 다음 동기화에서 다시 맞춥니다.

## 저장소 구조

```text
.
├── app/
│   ├── api/
│   │   ├── deps.py                 # 인증·승인 사용자 의존성
│   │   └── routes/                 # 인증, 사용자, 회의록, Google Calendar API
│   ├── core/
│   │   ├── config.py               # 환경변수 설정
│   │   ├── database.py             # SQLAlchemy 연결
│   │   ├── prompts.py              # 요약·추출·RAG 프롬프트
│   │   └── security.py             # JWT·비밀번호 처리
│   ├── models/                     # 사용자·회의록·PII·업무·청크·캘린더 모델
│   ├── repositories/               # 계정 소유권 필터가 적용된 DB 접근 계층
│   ├── schemas/                    # API 요청·응답 스키마
│   ├── services/                   # STT, 마스킹, 분석, 검색, 캘린더, 보고서
│   ├── static/                     # 브라우저 UI
│   ├── mcp_server.py               # FastMCP 도구와 Noting JWT 검증
│   └── main.py                     # FastAPI 진입점
├── data/
│   └── templates/                  # 보고서 템플릿
├── scripts/
│   ├── migrate_action_items_rag.py # 업무 임베딩·일정 변경 증분 마이그레이션
│   ├── migrate_analysis_jobs.py     # 백그라운드 분석 상태 컬럼 증분 마이그레이션
│   ├── migrate_transcript_archive.py # 회의·할 일 아카이브 증분 마이그레이션
│   ├── migrate_transcript_titles.py # 자동·수동 회의 제목 증분 마이그레이션
│   ├── migrate_user_identity_and_ownership.py # 실명·회의 소유권·PII 토큰 마이그레이션
│   ├── migrate_google_calendar.py  # Google OAuth 연결·일정 링크 테이블
│   └── seed_users.py                # 로컬 개발용 사용자 데이터
├── tests/                          # 단위 테스트
├── .env.example                    # 환경변수 예시
├── pyproject.toml
└── uv.lock
```

## 로컬 개발 환경

### 사전 요구사항

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 및 pgvector 확장
- Ollama와 설정한 생성·임베딩 모델
- 음성 인식을 사용할 경우 CLOVA Speech API 정보
- Google Calendar 연동 시 Google Cloud OAuth 웹 클라이언트와 HTTPS 도메인

### 의존성 설치

```powershell
uv sync
```

### 환경변수

`.env.example`을 복사해 `.env`를 만들고 실제 개발 환경 값을 입력합니다. 비밀 값이 포함된 `.env`는 Git에 커밋하지 않습니다.

| 변수 | 필수 | 기본값 | 설명 |
|---|---:|---|---|
| `ENVIRONMENT` | 아니요 | `development` | 실행 환경 이름 |
| `DEBUG` | 아니요 | `true` | 개발 디버그 설정 |
| `DATABASE_URL` | 예 | 없음 | PostgreSQL 연결 문자열 |
| `SECRET_KEY` | 예 | 없음 | JWT 서명 키 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 아니요 | `60` | 액세스 토큰 만료 시간 |
| `LLM_MODEL` | 아니요 | `gemma4:e2b` | Ollama 생성 모델 |
| `EMBED_MODEL` | 아니요 | `nomic-embed-text` | Ollama 임베딩 모델 |
| `OLLAMA_BASE_URL` | 아니요 | `http://localhost:11434` | Ollama API 주소 |
| `CLOVA_SPEECH_INVOKE_URL` | 음성 사용 시 | 빈 값 | CLOVA Speech 호출 주소 |
| `CLOVA_SPEECH_SECRET` | 음성 사용 시 | 빈 값 | CLOVA Speech API 키 |
| `GOOGLE_CLIENT_ID` | 캘린더 사용 시 | 빈 값 | Google OAuth 웹 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 캘린더 사용 시 | 빈 값 | Google OAuth 클라이언트 비밀 |
| `GOOGLE_CALENDAR_REDIRECT_URI` | 캘린더 사용 시 | 빈 값 | Google OAuth 콜백 주소 |
| `GOOGLE_CALENDAR_TIMEZONE` | 아니요 | `Asia/Seoul` | Google 일정 시간대 |
| `GOOGLE_CALENDAR_REMINDER_MINUTES` | 아니요 | `1440` | 일정 사전 알림 시간 |
| `TOKEN_ENCRYPTION_KEY` | 운영 시 권장 | `SECRET_KEY`에서 파생 | 저장된 Google 토큰 암호화 키 |
| `MCP_ISSUER_URL` | MCP 외부 사용 시 | `http://localhost:8000` | MCP 토큰 발급자 식별 URL |
| `MCP_RESOURCE_SERVER_URL` | MCP 외부 사용 시 | `http://localhost:8000/mcp` | MCP 리소스 서버 URL |

예시:

```dotenv
ENVIRONMENT=development
DEBUG=true
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/noting
SECRET_KEY=replace-with-a-long-random-value
ACCESS_TOKEN_EXPIRE_MINUTES=60

LLM_MODEL=gemma4:e2b
EMBED_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://localhost:11434

CLOVA_SPEECH_INVOKE_URL=
CLOVA_SPEECH_SECRET=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_CALENDAR_REDIRECT_URI=https://your-domain.example/calendar/google/callback
GOOGLE_CALENDAR_TIMEZONE=Asia/Seoul
GOOGLE_CALENDAR_REMINDER_MINUTES=1440
TOKEN_ENCRYPTION_KEY=replace-with-a-separate-long-random-value

MCP_ISSUER_URL=https://your-domain.example
MCP_RESOURCE_SERVER_URL=https://your-domain.example/mcp
```

`TOKEN_ENCRYPTION_KEY`를 변경하면 기존에 저장한 Google OAuth 토큰을 복호화할 수 없으므로 해당 사용자는 Calendar를 다시 연결해야 합니다.

### 데이터베이스

데이터베이스에 `vector` 확장이 활성화돼 있어야 합니다.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

현재 저장소는 기본 테이블이 구성된 데이터베이스를 전제로 하며, 완전한 초기 스키마 마이그레이션 체인은 아직 포함하지 않습니다. `scripts/migrate_user_identity_and_ownership.py`는 사용자 표시 이름, 회의 소유 계정, 위치가 구분된 PII 토큰 컬럼을 추가합니다. 기존 소유자 없는 회의는 기본적으로 `acc_user` 계정에 귀속하고 해당 표시 이름은 `김철수`로 설정합니다. 다른 계정을 사용하려면 실행 전에 `LEGACY_TRANSCRIPT_OWNER_USERNAME`, `LEGACY_OWNER_DISPLAY_NAME` 환경변수를 지정합니다. 기존 일반 `[이름]` 마스킹은 저장된 PII 순서에 따라 번호 토큰으로 연결되며 해당 회의는 재분석 대기 상태가 됩니다. 사용자별 담당 업무를 다시 추출하려면 배포 후 기존 회의를 한 번 재분석해야 합니다.

기존 스키마에 증분 마이그레이션을 적용할 때:

```powershell
uv run python scripts/migrate_action_items_rag.py
uv run python scripts/migrate_transcript_titles.py
uv run python scripts/migrate_analysis_jobs.py
uv run python scripts/migrate_transcript_archive.py
uv run python -m scripts.migrate_user_identity_and_ownership
uv run python scripts/migrate_google_calendar.py
```

`migrate_google_calendar.py`는 기존 `google_calendar_connections` 테이블에 Google 고정 사용자 식별자 컬럼과 인덱스를 추가하고, 로그아웃 상태에서 액세스 토큰을 제거할 수 있도록 해당 컬럼을 nullable로 변경합니다. 운영 서버에서는 애플리케이션을 재시작하기 전에 이 마이그레이션을 먼저 실행해야 합니다.

로컬 개발용 사용자를 추가할 때:

```powershell
uv run python scripts/seed_users.py
```

`seed_users.py`의 계정과 비밀번호는 로컬 개발 전용입니다. 운영 환경에서는 실행하지 말고 별도의 사용자 프로비저닝 절차를 사용해야 합니다.

### 모델 준비

Ollama에서 `.env`에 지정한 생성 모델과 임베딩 모델을 사용할 수 있는지 확인합니다.

```powershell
ollama list
```

### 애플리케이션 실행

```powershell
uv run uvicorn app.main:app --reload
```

기본 접근 주소:

- Web UI: `http://127.0.0.1:8000/ui/`
- API 문서: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`
- MCP endpoint: `http://127.0.0.1:8000/mcp/`

브라우저 녹음은 보안 컨텍스트가 필요합니다. 로컬에서는 `localhost` 또는 `127.0.0.1`을 사용하고, 운영 환경에서는 HTTPS를 적용해야 합니다.

Google Cloud Console에서는 Google Calendar API를 활성화하고 OAuth 클라이언트를 **웹 애플리케이션** 유형으로 생성합니다. 운영 리디렉션 URI는 `.env`와 동일한 `https://서비스도메인/calendar/google/callback`을 등록해야 합니다. 비밀값은 저장소에 커밋하지 않습니다.

## 주요 API

| Method | Endpoint | 설명 |
|---|---|---|
| `POST` | `/auth/signup` | 사용자 가입 |
| `POST` | `/auth/login` | JWT 로그인 |
| `GET` | `/me` | 현재 사용자 조회 |
| `GET` | `/users/pending` | 같은 부서 가입 대기자 조회 |
| `POST` | `/users/{user_id}/approve` | 가입 승인 |
| `POST` | `/transcripts` | 텍스트 회의록 생성 및 마스킹 |
| `POST` | `/transcripts/upload` | 음성 업로드, STT 및 마스킹 |
| `PUT` | `/transcripts/{id}` | 검토한 회의록 저장 |
| `POST` | `/transcripts/{id}/analysis` | 요약·업무 추출 및 RAG 인덱싱 |
| `PATCH` | `/transcripts/{id}/title` | 사용자가 회의 제목 수정 |
| `POST` | `/transcripts/search` | 현재 계정의 회의록 검색 |
| `POST` | `/transcripts/ask` | 근거 기반 회의록 Q&A |
| `GET` | `/transcripts/{id}/tasks` | 추출된 업무 조회 |
| `PATCH` | `/transcripts/{id}/tasks/{task_id}` | 업무 상태 변경 |
| `GET` | `/transcripts/{id}/schedule-change-candidates` | 일정 변경 후보 조회 |
| `GET` | `/transcripts/{id}/pii` | 현재 계정 관리자용 PII 원문 조회 |
| `GET` | `/transcripts/{id}/report.pdf` | PDF 보고서 다운로드 |
| `GET` | `/calendar/google/status` | 현재 사용자의 Google Calendar 연결 상태 |
| `GET` | `/calendar/google/connect` | Google OAuth 승인 URL 생성 |
| `GET` | `/calendar/google/callback` | Google OAuth 콜백과 토큰 저장 |
| `POST` | `/calendar/google/sync` | 본인 업무와 Google 일정 동기화 |
| `GET` | `/calendar/google/events` | 동기화된 향후 Noting 일정 조회 |
| `POST` | `/calendar/google/events` | 사용자 요청에 따른 수동 일정 생성 |
| `DELETE` | `/calendar/google/disconnect` | Google 연결과 저장 토큰 제거 |
| `POST` | `/mcp/` | MCP Streamable HTTP 메시지 처리 |

세부 요청·응답 스키마는 실행 중인 서비스의 `/docs`에서 확인할 수 있습니다.

## 테스트 및 검증

단위 테스트:

```powershell
uv run --group dev pytest -q
```

현재 테스트 범위:

- 텍스트 청킹 경계와 입력 검증
- UI 및 루트 라우팅
- 한국어 표현 변형과 RAG 재정렬
- 근거 부족 판정
- 업무 상태 값 검증
- LangGraph Agentic RAG 노드 분기와 실행 trace
- MCP 도구 등록 및 비인증 요청 차단
- 한국어 기한 해석, Google 일정 본문과 하루 전 알림 생성
- Google OAuth state 서명·검증

현재 전체 자동 테스트 결과:

```text
73 passed
```

2026년 7월 23일 로컬 확장 평가 결과:

| 항목 | 결과 |
|---|---:|
| 정답 검색 Top-1 | 39/40, 97.5% |
| 정답 검색 Top-3 | 40/40, 100% |
| 근거 기반 답변 교차 검증 | 10/10 |
| 근거 없는 질문 차단 | 5/5 |
| 범위 밖 질문 차단 | 3/3 |
| 부서 격리 | 2/2 |

이 수치는 23개 합성 회의록과 50개 고유 질문으로 수행한 로컬 검증 결과입니다. 실제 운영 데이터 전체의 성능을 보장하지 않으며, 긴 회의록과 부서별 실제 용어를 포함한 추가 평가가 필요합니다.

## 운영 전 확인사항

- PostgreSQL Row-Level Security 및 감사 로그 적용
- 비밀 관리 시스템을 통한 DB·JWT·CLOVA 키 관리
- HTTPS, CORS, 요청 크기 제한, rate limiting 설정
- CLOVA Speech·Ollama 장애에 대한 재시도 및 사용자 오류 메시지 표준화
- 동기식 LLM·STT 작업의 비동기 작업 큐 전환 검토
- 전체 스키마 마이그레이션과 롤백 절차 구축
- 실제 회의록 기반 검색·마스킹·업무 추출 회귀 평가
- Google OAuth 운영 승인, 테스트 사용자와 리디렉션 URI 점검
- MCP 공개 연동 시 OAuth Authorization Server 구성
- CI에서 단위·통합 테스트 자동 실행
- 데이터 보존 기간과 PII 삭제 정책 수립

## 알려진 제약

- CLOVA Speech와 Ollama 호출은 현재 동기식이며 처리 중 요청이 오래 유지될 수 있습니다.
- 임베딩 실패는 일부 경로에서 기능 제한 또는 `503`으로 처리하지만, 공통 재시도 정책은 아직 없습니다.
- 개인정보 마스킹은 규칙 기반 탐지이므로 실제 운영 전 별도의 정확도 검증이 필요합니다.
- 계정별 회의 소유권 검사는 애플리케이션 계층에 구현돼 있으며 DB 자체 RLS는 적용되지 않았습니다.
- 초기 데이터베이스를 처음부터 생성하는 통합 마이그레이션은 아직 제공하지 않습니다.
- 자동화된 브라우저 E2E 및 외부 STT 통합 테스트는 현재 테스트 범위에 포함되지 않습니다.
- Google Calendar 연동에는 Google Cloud OAuth 설정, 사용자 동의와 HTTPS 도메인이 필요합니다.
- 날짜가 불명확한 업무는 Noting에는 저장되지만 Google Calendar에는 자동 등록되지 않습니다.
- MCP는 현재 Noting JWT 직접 전달 방식이며 범용 클라이언트용 OAuth 로그인 서버는 포함하지 않습니다.

## 개발 원칙

- 모든 회의·업무·RAG DB 조회에는 사용자 승인 상태와 `owner_user_id` 범위를 반영합니다.
- LLM 출력은 권한 판단에 사용하지 않으며, 권한은 애플리케이션과 DB 쿼리에서 결정합니다.
- 사용자 수정 후에는 이전 분석·임베딩을 무효화합니다.
- 회의록에 없는 사실을 생성하지 않도록 프롬프트와 근거 게이트를 함께 적용합니다.
- 스키마 변경에는 재실행 가능한 마이그레이션과 롤백 계획을 포함합니다.
- 기능 변경 시 관련 테스트와 사용자 문서를 함께 갱신합니다.

## 변경 기여 절차

1. 변경 목적과 영향 범위를 이슈 또는 작업 설명에 기록합니다.
2. 기능과 수정 작업을 분리한 브랜치에서 개발합니다.
3. 비밀 값과 실제 개인정보가 커밋되지 않았는지 확인합니다.
4. 단위 테스트와 관련 로컬 검증을 실행합니다.
5. DB 스키마·환경변수·API 변경 사항을 README와 마이그레이션에 반영합니다.
6. Pull Request에서 권한 경계, 데이터 무효화, 실패 처리 영향을 검토합니다.
