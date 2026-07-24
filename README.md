# Noting

회의 음성을 부서별 업무 데이터로 전환하는 AI 회의록 관리 서비스입니다. 음성 인식 결과를 사람이 검토한 뒤 요약, 일정 및 요청사항 추출, 회의록 기반 질의응답, 보고서 생성을 하나의 웹 흐름으로 제공합니다.

Noting은 회계·경영·영업 부서가 하나의 AI 인프라를 공유하되, 데이터 조회와 검색 범위는 부서 단위로 분리하도록 설계되었습니다. LLM에는 마스킹된 텍스트만 전달하며, 개인정보 원문은 별도 테이블에 저장하고 같은 부서 관리자에게만 제공합니다.

## 주요 기능

- 브라우저 녹음 및 음성 파일 업로드
- CLOVA Speech 기반 한국어 STT
- 이름·전화번호 마스킹 및 원문 분리 저장
- 회의록 저장·수정 후 별도 버튼 없이 자동 분석
- Gemma 기반 자동 회의 제목, 요약과 할 일·담당자·기한·요청사항 추출
- 날짜별 회의 목록과 회의 상세 화면, 사용자 제목 수정
- PostgreSQL·pgvector 기반 부서별 RAG 검색
- 회의록 근거 기반 Q&A와 근거 부족·범위 밖 질문 차단
- 유사 업무 탐지 및 일정 변경 후보 확인
- 업무 상태 관리와 캘린더형 대시보드
- 텍스트 및 PDF 보고서 생성
- 부서 관리자 기반 가입 승인과 개인정보 원문 조회

## 시스템 구성

```mermaid
flowchart LR
    U["브라우저 UI"] --> API["FastAPI"]
    API --> AUTH["인증·승인·부서 권한"]
    API --> STT["CLOVA Speech"]
    API --> MASK["개인정보 마스킹"]
    MASK --> DB[("PostgreSQL + pgvector")]
    API --> EMB["Ollama / nomic-embed-text"]
    API --> LLM["Ollama / Gemma"]
    DB --> RET["부서 필터 + 하이브리드 검색"]
    EMB --> RET
    RET --> LLM
    LLM --> API
    API --> REPORT["텍스트·PDF 보고서"]
```

### 데이터 처리 흐름

1. 사용자가 브라우저에서 녹음하거나 음성 파일을 업로드합니다.
2. FastAPI가 CLOVA Speech를 호출해 한국어 텍스트를 생성합니다.
3. 이름과 전화번호를 마스킹하고, 마스킹 본문과 개인정보 원문을 분리 저장합니다.
4. 저장 직후 Gemma가 회의 제목, 요약과 업무 항목을 구조화된 JSON으로 자동 추출합니다.
5. 사용자가 마스킹된 회의록을 수정하면 기존 분석을 무효화하고 자동으로 다시 분석합니다.
6. 회의록 청크·요약·업무 항목을 임베딩해 pgvector에 저장합니다.
7. 질문 시 같은 부서의 데이터만 검색하고, 벡터 및 어휘 점수를 결합해 근거를 재정렬합니다.
8. 충분한 근거가 있을 때만 Gemma가 답변하며, 결과에는 근거 문서와 차단 상태가 함께 반환됩니다.

회의록이 수정되면 이전 요약, 업무 항목 및 검색 청크를 제거한 뒤 자동으로 다시 분석합니다. 사용자가 직접 수정한 회의 제목은 재분석해도 유지됩니다.

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
| Reporting | ReportLab | PDF 회의 보고서 생성 |
| Package management | uv | 의존성 및 가상환경 관리 |

별도의 에이전트 프레임워크는 사용하지 않습니다. 처리 순서와 권한 경계가 명확한 서비스이므로 FastAPI 서비스 계층에서 파이프라인을 직접 구성해 동작과 실패 지점을 추적할 수 있도록 했습니다.

## 보안 및 권한 모델

### 사용자 상태

- 신규 사용자는 `대기` 상태로 등록됩니다.
- 같은 부서 관리자가 승인해야 서비스 기능을 사용할 수 있습니다.
- 승인 또는 거절 작업은 관리자 API에서 처리합니다.

### 데이터 접근

- 회의록, 검색 청크, 업무 항목은 요청 사용자의 부서 조건으로 조회합니다.
- 회계·경영·영업 데이터는 repository 쿼리 단계에서 상호 격리됩니다.
- 개인정보 원문 조회는 같은 부서의 관리자에게만 허용됩니다.
- LLM과 임베딩 모델에는 마스킹된 회의 내용만 전달됩니다.

현재 부서 격리는 애플리케이션 쿼리 계층에서 수행합니다. 운영 환경에서는 PostgreSQL Row-Level Security, 감사 로그, 비밀 관리 시스템을 추가하는 것을 권장합니다.

## RAG 검색 구조

검색은 단일 벡터 유사도에만 의존하지 않습니다.

1. pgvector에서 최종 반환 개수보다 넓은 후보군을 조회합니다.
2. 한국어 표현과 회의 도메인 동의어를 정규화합니다.
3. 벡터 유사도 65%와 어휘 유사도 35%를 결합해 후보를 재정렬합니다.
4. 최고 검색 점수와 명시적 어휘 근거가 부족하면 LLM 호출 전에 차단합니다.
5. LLM 답변이 근거 부족을 나타내는 경우 `insufficient_context` 상태로 교정합니다.

질의응답 API는 다음 상태를 함께 반환합니다.

- `grounded`: 답변이 검색 근거를 기반으로 생성됐는지 여부
- `blocked`: 질문 또는 근거 부족으로 답변이 차단됐는지 여부
- `blocked_reason`: `out_of_scope`, `low_similarity`, `insufficient_context` 등 차단 사유
- `sources`: 답변 생성에 사용한 같은 부서의 회의록 근거

## 저장소 구조

```text
.
├── app/
│   ├── api/
│   │   ├── deps.py                 # 인증·승인 사용자 의존성
│   │   └── routes/                 # 인증, 사용자, 회의록 API
│   ├── core/
│   │   ├── config.py               # 환경변수 설정
│   │   ├── database.py             # SQLAlchemy 연결
│   │   ├── prompts.py              # 요약·추출·RAG 프롬프트
│   │   └── security.py             # JWT·비밀번호 처리
│   ├── models/                     # 사용자·회의록·PII·업무·청크 모델
│   ├── repositories/               # 부서 필터가 적용된 DB 접근 계층
│   ├── schemas/                    # API 요청·응답 스키마
│   ├── services/                   # STT, 마스킹, 분석, 검색, 보고서
│   ├── static/                     # 브라우저 UI
│   └── main.py                     # FastAPI 진입점
├── data/
│   └── templates/                  # 보고서 템플릿
├── scripts/
│   ├── migrate_action_items_rag.py # 업무 임베딩·일정 변경 증분 마이그레이션
│   ├── migrate_analysis_jobs.py     # 백그라운드 분석 상태 컬럼 증분 마이그레이션
│   ├── migrate_transcript_titles.py # 자동·수동 회의 제목 증분 마이그레이션
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
```

### 데이터베이스

데이터베이스에 `vector` 확장이 활성화돼 있어야 합니다.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

현재 저장소는 기본 테이블이 구성된 데이터베이스를 전제로 하며, 완전한 초기 스키마 마이그레이션 체인은 아직 포함하지 않습니다. `scripts/migrate_action_items_rag.py`는 기존 `action_items` 테이블에 상태, 임베딩 및 일정 변경 관계를 추가하고, `scripts/migrate_transcript_titles.py`는 기존 `transcripts` 테이블에 자동·수동 제목 필드를 추가합니다. `scripts/migrate_analysis_jobs.py`는 긴 LLM 분석을 백그라운드에서 추적하기 위한 상태와 오류 컬럼을 추가합니다.

기존 스키마에 증분 마이그레이션을 적용할 때:

```powershell
uv run python scripts/migrate_action_items_rag.py
uv run python scripts/migrate_transcript_titles.py
uv run python scripts/migrate_analysis_jobs.py
```

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

브라우저 녹음은 보안 컨텍스트가 필요합니다. 로컬에서는 `localhost` 또는 `127.0.0.1`을 사용하고, 운영 환경에서는 HTTPS를 적용해야 합니다.

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
| `POST` | `/transcripts/search` | 같은 부서 회의록 검색 |
| `POST` | `/transcripts/ask` | 근거 기반 회의록 Q&A |
| `GET` | `/transcripts/{id}/tasks` | 추출된 업무 조회 |
| `PATCH` | `/transcripts/{id}/tasks/{task_id}` | 업무 상태 변경 |
| `GET` | `/transcripts/{id}/schedule-change-candidates` | 일정 변경 후보 조회 |
| `GET` | `/transcripts/{id}/pii` | 같은 부서 관리자용 PII 원문 조회 |
| `GET` | `/transcripts/{id}/report.pdf` | PDF 보고서 다운로드 |

세부 요청·응답 스키마는 실행 중인 서비스의 `/docs`에서 확인할 수 있습니다.

## 테스트 및 검증

단위 테스트:

```powershell
uv run python -m unittest discover -s tests -v
```

현재 테스트 범위:

- 텍스트 청킹 경계와 입력 검증
- UI 및 루트 라우팅
- 한국어 표현 변형과 RAG 재정렬
- 근거 부족 판정
- 업무 상태 값 검증

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
- CI에서 단위·통합 테스트 자동 실행
- 데이터 보존 기간과 PII 삭제 정책 수립

## 알려진 제약

- CLOVA Speech와 Ollama 호출은 현재 동기식이며 처리 중 요청이 오래 유지될 수 있습니다.
- 임베딩 실패는 일부 경로에서 기능 제한 또는 `503`으로 처리하지만, 공통 재시도 정책은 아직 없습니다.
- 개인정보 마스킹은 규칙 기반 탐지이므로 실제 운영 전 별도의 정확도 검증이 필요합니다.
- 부서 격리는 애플리케이션 계층에 구현돼 있으며 DB 자체 RLS는 적용되지 않았습니다.
- 초기 데이터베이스를 처음부터 생성하는 통합 마이그레이션은 아직 제공하지 않습니다.
- 자동화된 브라우저 E2E 및 외부 STT 통합 테스트는 현재 테스트 범위에 포함되지 않습니다.

## 개발 원칙

- 모든 DB 조회에는 사용자 승인 상태와 부서 범위를 반영합니다.
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
