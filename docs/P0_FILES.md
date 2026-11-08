# P0 文件树与变更清单

完整交付树（不含依赖、构建输出和本地运行数据）：

```text
.github/workflows/ci.yml
.gitignore
README.md
backend/app/__init__.py
backend/app/main.py
backend/app/migrations/001_initial.sql
backend/app/model_cli.py
backend/app/models.py
backend/app/providers.py
backend/app/store.py
backend/app/tools.py
backend/app/workspace.py
backend/config/providers.example.json
backend/pyproject.toml
backend/tests/fixtures/challenges.json
backend/tests/test_core.py
backend/tests/test_providers.py
docs/ARCHITECTURE.md
docs/MODEL_PROVIDERS.md
docs/OSS_REVIEW_20261107.md
docs/P0_API.md
docs/P0_FILES.md
docs/P0_RUNBOOK.md
docs/P0_TEST_REPORT.md
docs/WORK_PLAN.md
docs/WRITEUP_INTEGRITY_SPEC.md
docs/contracts.json
docs/openapi.json
frontend/index.html
frontend/package-lock.json
frontend/package.json
frontend/src/App.vue
frontend/src/main.ts
frontend/tsconfig.json
frontend/vite.config.ts
scripts/backend.ps1
scripts/check.ps1
scripts/frontend.ps1
```

变更：README.md 追加导航；原有四份 docs 规范保持不变。其余上述文件均为新增。
