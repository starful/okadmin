# GitHub에 푸시하기 (민감 정보)

[starful/okadmin](https://github.com/starful/okadmin) 은 **코드만** 올립니다. 키·토큰·로컬 `.env` 는 **절대 커밋하지 마세요.**

## 절대 커밋하면 안 되는 것

| 경로 | 내용 |
|------|------|
| `.env` | API 키, OAuth secret, Flask secret |
| `secrets/firebase-key.json` | 서비스 계정 private key |
| `gsc-token.json` | OAuth 클라이언트 secret |
| `gsc-oauth-user.json` | GSC 사용자 refresh token |
| `ops/logs/*.log` | 배포 로그, GCP 프로젝트·레포 경로 |
| `command.txt` | Cloud Run 배포 명령 (로컬 메모) |

이미 `.gitignore` 에 등록되어 있습니다.

## 푸시 전 체크 (필수)

```bash
cd /opt/work/okadmin
git init   # 최초 1회
git add -n .   # 실제 추가될 파일만 미리보기
git status
```

`git add -n` 결과에 위 파일이 **하나도 없어야** 합니다.

추가로 시크릿 스캔 (선택):

```bash
# ripgrep 설치되어 있을 때
rg -l 'AIza[0-9A-Za-z_-]{20,}|GOCSPX-|private_key' --glob '!.git' .
# → 매칭되면 .gitignore 추가 또는 파일 삭제
```

## 최초 푸시

```bash
git remote add origin https://github.com/starful/okadmin.git
git add .
git commit -m "Initial okadmin (Work Hub)"
git push -u origin main
```

브랜치가 `master` 이면 `git branch -M main` 후 push.

## 클론 후 로컬 설정

```bash
cp .env.example .env
./scripts/fetch_secrets.sh   # GCP Secret Manager (권한 필요)
# GSC: gsc-token.json 은 GCP Console에서 별도 다운로드 → oauth/gsc/setup
```

`WORK_ROOT`, `SITES_YAML` 은 각자 환경에 맞게 `.env` 에 설정.

## 이미 실수로 푸시했다면

1. 해당 키를 **GCP / Google Cloud Console에서 즉시 폐기·재발급**
2. `git filter-repo` 또는 GitHub secret scanning 대응
3. force push로 히스토리 제거 (공개 repo면 키는 이미 유출된 것으로 간주)
