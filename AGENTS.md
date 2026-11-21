# SALGU

## Structure

```
AI/    # model, inference
BE/    # backend
FE/    # frontend
Data/  # datasets
```

## Commit Convention

```
<type>: <subject>

[body]
```

### Types

- `feat` — new feature
- `fix` — bug fix
- `refactor` — no behavior change
- `docs` — documentation only
- `style` — formatting, no logic change
- `test` — add/update tests
- `chore` — build, config, deps

### Rules

- subject ≤ 50 chars, no trailing period
- 핵심만 간결하게 — what & why
- 1 commit = 1 logical change
- body는 필요할 때만, 72 chars wrap
- `수정`, `update`, `wip`, `fix bug` 같은 모호한 메시지 금지

### Examples

```
feat: 회원가입 API 추가
fix: 로그인 버튼 중복 클릭 시 요청 2회 전송 방지
refactor: 전처리 로직 모듈 분리
docs: README에 실행 방법 추가
chore: .env를 .gitignore에 추가
```
