# 已执行测试基线

日期：2026-11-07。此报告是基线实测，未把实施方案的未来测试写为通过。

## 1. 环境与隔离

Windows PowerShell；Python 3.14.7；SQLite 3.50.4；pytest 9.1.1；Ruff 0.14.10；Node.js v24.19.0；npm 11.17.0。
环境已有依赖：FastAPI0.142.2、Pydantic2.13.5、httpx0.28.1、python-multipart0.0.20；与P1-1 pyproject锁定值相符。未将生产代码安装进全局环境，未调用真实模型。

P0.1/P1-1以Git固定ref的独立快照测试，不覆盖用户目录。pytest设置 CTF_RUN_LIVE_MODEL=0、PYTHONDONTWRITEBYTECODE=1、PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，使用 `-p no:cacheprovider`；真实Provider测试明确跳过，禁用无关自动插件，不依赖真实凭证。Artifact测试使用其既有tmp_path合成材料，不接触比赛文件。

## 2. 结果按基线分别报告

| 基线/检查 | 结果 | 说明 |
|---|---|---|
| 当前PR #3 00e9436，根目录pytest | no tests ran；pytest exit=5 | 没有应用pytest用例，不能报为全仓pytest通过 |
| 当前PR #3，Python KAT | 195 frozen cases PASS；6 fresh-process checks | 仅离线参考实现 |
| 当前PR #3，Node KAT | 195 frozen cases PASS；6 fresh-process checks | 同上 |
| 当前PR #3，cross-language | 195 exact results PASS；56 positive/139 exact error-code | Canonical/framing/message/MAC bytes一致 |
| 当前PR #3，KAT SHA256SUMS | Git原始blob及专用原字节快照4/4匹配 | 见行尾说明 |
| 当前PR #3，Ruff scripts/kat | All checks passed | --no-cache |
| P0.1 ed4850d，backend pytest | 28 passed, 2 skipped；exit0 | 来源P0独立快照，不是当前docs分支的backend |
| P0.1，backend Ruff | All checks passed | app/tests |
| P1-1 778bad7，backend pytest | 75 passed, 3 skipped；exit0 | 包含P0继承用例，不将两组通过数相加 |
| P1-1，backend Ruff | All checks passed | app/tests |
| P0/P1-1共同frontend | npm ci成功；vue-tsc/Vite build成功 | 两个ref的frontend tree完全相同，构建P1-1快照验证共同代码 |

frontend tree SHA 均为 b5f517137ccdfa48aba877eff3a3301ccbd96069。Vue3.5.45、Vite7.3.7，输出11个模块的生产bundle。npm提示esbuild安装脚本allow-scripts信息，但本次构建退出0；本报告不声称做过浏览器E2E或依赖安全审计。

跳过原因经定向`-rs`检查：P0的core symlink权限不可用及live Provider未显式启用；P1-1另外增加artifact symlink权限不可用，共3项。Windows junction测试已在完整P1-1套件中执行；不把两个symlink跳过当作其权限边界已验证。

## 3. 关键命令与实际输出

backend各自在其固定快照的backend目录：

```text
python -m pytest -q -p no:cacheprovider
python -m ruff check --no-cache app tests

# P0.1
28 passed, 2 skipped in 4.06s
pytest_exit=0
# P1-1
75 passed, 3 skipped in 8.68s
pytest_exit=0
```

KAT在当前提交的独立原始字节快照运行，report路径位于checkout外：

```text
python -B scripts/kat/stream_content_v1.py --fixture tests/fixtures/stream_content_v1_kat.json --report ../design-python.json
node scripts/kat/stream_content_v1.mjs --fixture tests/fixtures/stream_content_v1_kat.json --report ../design-node.json
python -B scripts/kat/compare_reports.py --fixture tests/fixtures/stream_content_v1_kat.json --python ../design-python.json --node ../design-node.json

Python: 195 frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS
Node.js: 195 frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS
Cross-language: 195 exact frozen results PASS (56 positive, 139 exact error-code cases)
Canonical/framing/message hex and both MACs: byte-for-byte equal
fixture_sha256=92a790c122f0f60a56a60b12ee5d36e77bfdb2a379f65f46cf7f9c291d7c0bd6
SHA256SUMS: True
```

共同frontend：

```text
npm ci --no-audit --no-fund
npm run build
vue-tsc --noEmit && vite build
11 modules transformed
built in 803ms
```

## 4. 行尾与完整性事实

本机Git core.autocrlf=true，checkout及本次git archive导出的文本会成为CRLF；初次直接运行KAT仍195条通过，但工作副本fixture SHA为0703afe2b0e5dda915801d071431ba8d6d4c174dfa781480c95832ea249fbeae，直接按LF清单检查会失败。

进一步直接用 `subprocess.check_output(['git','cat-file','blob','HEAD:path'])`读取二进制Git blob：四个目标文件CRLF数量均为0，SHA均匹配既有清单；并与a577e9c的对应blob一致。随后只把**独立scratch KAT快照**恢复为这些原始bytes，重新运行完整KAT/cross和4项checksum，得到上面的92a790.../True。没有改写checkout已有文件、fixture expected或协议来“修正”校验值。

这属于本地checkout行尾转换，不是仓库Golden被修改。后续CI/实现应按Git blob或约定LF验证；是否新增.gitattributes另行审查，本轮不改已有项目文件。

## 5. 未覆盖项

没有当前分支上的生产backend集成测试，因为代码尚未整合。没有创建/验证003/004，没有实现ToolLifecycleService/ModelStreamAuditService/AuditStore/Keyring/FakeRunner生产接口；没有真实模型、真实工具、OS密钥、审批认证、容器/网络、Writeup验收。195条KAT不能替代这些测试。

基线测试通过不消除G01–G06审查gate。本包需要ChatGPT先审接口/拆分与迁移安排，再下发具体实现。
