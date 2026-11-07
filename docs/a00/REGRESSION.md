# A00 实际回归命令与输出

整合 HEAD：`e581144c68bf05932334decc4babc9b61a764bb5`。

运行环境变量：`CTF_RUN_LIVE_MODEL=0`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONIOENCODING=utf-8`。没有打印或读取凭证。前端 npm install 只安装固定 lockfile 的开发构建依赖，不是模型网络调用。

## p0-backend

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\backend
$ python -B -m pytest tests/test_core.py tests/test_providers.py tests/test_model_audit.py -ra -p no:cacheprovider
============================= test session starts =============================

platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0

rootdir: C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\backend

configfile: pyproject.toml

collected 30 items



tests\test_core.py .............s                                        [ 46%]

tests\test_providers.py ..........s                                      [ 83%]

tests\test_model_audit.py .....                                          [100%]



=========================== short test summary info ===========================

SKIPPED [1] tests\test_core.py:126: Symlink privilege unavailable

SKIPPED [1] tests\test_providers.py:167: Requires explicit opt-in and legal provider credentials

======================== 28 passed, 2 skipped in 2.70s ========================


exit_code=0
```

## p11-backend

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\backend
$ python -B -m pytest -ra -p no:cacheprovider
============================= test session starts =============================

platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0

rootdir: C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\backend

configfile: pyproject.toml

testpaths: tests

collected 78 items



tests\test_artifacts.py .......................s........................ [ 61%]

                                                                         [ 61%]

tests\test_core.py .............s                                        [ 79%]

tests\test_model_audit.py .....                                          [ 85%]

tests\test_providers.py ..........s                                      [100%]



=========================== short test summary info ===========================

SKIPPED [1] tests\test_artifacts.py:532: Symlink privilege unavailable

SKIPPED [1] tests\test_core.py:126: Symlink privilege unavailable

SKIPPED [1] tests\test_providers.py:167: Requires explicit opt-in and legal provider credentials

======================== 75 passed, 3 skipped in 7.61s ========================


exit_code=0
```

## ruff

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\backend
$ python -B -m ruff check --no-cache app tests
All checks passed!

exit_code=0
```

## npm-ci

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\frontend
$ npm.cmd ci --no-audit --no-fund

added 45 packages in 4s
npm warn allow-scripts 1 package has install scripts not yet covered by allowScripts:
npm warn allow-scripts   esbuild@0.28.2 (postinstall: node install.js)
npm warn allow-scripts
npm warn allow-scripts Run `npm approve-scripts --allow-scripts-pending` to review, or `npm approve-scripts <pkg>` to allow.

exit_code=0
```

## typescript

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\frontend
$ npm.cmd exec vue-tsc -- --noEmit

exit_code=0
```

## frontend-build

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit\frontend
$ npm.cmd run build

> ctf-workbench-ui@0.1.0 build
> vue-tsc --noEmit && vite build

vite v7.3.7 building client environment for production...
transforming...
✓ 11 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                  0.34 kB │ gzip:  0.26 kB
dist/assets/index-C8sSuNfY.css   0.43 kB │ gzip:  0.30 kB
dist/assets/index-D7KxwOwk.js   73.03 kB │ gzip: 29.02 kB
✓ built in 791ms

exit_code=0
```

## kat-python

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit
$ python -B scripts/kat/stream_content_v1.py --fixture tests/fixtures/stream_content_v1_kat.json --report C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\a00-evidence\python-results.json
Python: 195 frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS


exit_code=0
```

## kat-node

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit
$ node scripts/kat/stream_content_v1.mjs --fixture tests/fixtures/stream_content_v1_kat.json --report C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\a00-evidence\node-results.json
Node.js: 195 frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS

exit_code=0
```

## kat-compare

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit
$ python -B scripts/kat/compare_reports.py --fixture tests/fixtures/stream_content_v1_kat.json --python C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\a00-evidence\python-results.json --node C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\a00-evidence\node-results.json
Cross-language: 195 exact frozen results PASS (56 positive, 139 exact error-code cases)

Canonical/framing/message hex and both MACs: byte-for-byte equal

fixture_sha256=92a790c122f0f60a56a60b12ee5d36e77bfdb2a379f65f46cf7f9c291d7c0bd6


exit_code=0
```

## sha256-check

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
92a790c122f0f60a56a60b12ee5d36e77bfdb2a379f65f46cf7f9c291d7c0bd6  tests/fixtures/stream_content_v1_kat.json  OK
1e3437d07a47fad6e6c4e54ad9c789d07947ab7ba4a58546002044bd697360c1  scripts/kat/stream_content_v1.py  OK
114f2279cdc15cc1f01d8ef388301fad0412d60439e59e2da574f12b516ebf00  scripts/kat/stream_content_v1.mjs  OK
d3c6f7a13d820150a2ec9b79cef187ae0e77da949009888299f919a90332cdd4  scripts/kat/compare_reports.py  OK
4/4 checksums PASS
```

## compatibility

```text
HEAD=e581144c68bf05932334decc4babc9b61a764bb5
cwd=C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\p1-2a-audit
$ python -B C:\Users\28746\Documents\Codex\2026-11-07\ctf-agent-workbench-p0-https-github\work\a00-evidence\verify_compatibility.py
{

  "source_p11_files_identical": 47,

  "design_files_preserved_except_readme": 13,

  "readme_equals_p11": true,

  "historical_event_hash": "05c9cc5912383e872e9d6379b5ef06c33699cd5b6fcaccfeef342ad46aa24d02",

  "historical_event_body_sha256": "9b7be21db6f92c6ddfadf33891384babf84ff17344c13c9b7dac5489080baf19",

  "canonical_bytes_equal": true,

  "old_body_bytes_preserved": true,

  "event_heads_preserved": true,

  "migrations": [

    "001_initial.sql",

    "002_artifacts.sql"

  ],

  "artifact_source_link_preserved": true,

  "same_challenge_dedup_no_extra_event": true,

  "restart_all_event_artifact_rows_unchanged": true,

  "download_sha256": "7c41464348d8fd79cdf062cd7035d287ad664d17033da406ad969a3f556e7906",

  "safety_health": {

    "status": "ok",

    "execution_enabled": false,

    "model_network_enabled": false,

    "artifact_max_bytes": 52428800

  },

  "scope": "Synthetic compatibility only; no real models/tools/keys/attachments",

  "fixed_p11_database_all_rows_preserved": true,

  "fixed_p11_source_event_id_preserved": true

}


exit_code=0
```
