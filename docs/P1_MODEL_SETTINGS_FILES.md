# P1 模型服务设置修改文件清单

- 分支：`feat/p1-model-settings`
- 基准：P0 冻结候选 `D:\CTF-worktrees\p0-frozen`
- 增量 diff：`verification/p1-model-settings/incremental.diff`
- 完整 diff：`verification/p1-model-settings/complete.diff`
- 说明：本清单不含自身；SHA-256 为本清单生成时工作树字节。

| 状态 | 文件 | 大小 | SHA-256 |
|---|---|---|---|
| `M` | `.gitignore` | 342 | `077c3816a52a032f5f3d682878aab313a0a74780299080f41054d32f93c1012e` |
| `M` | `README.md` | 4711 | `53251f957ee44d3df155e86571436048f717e760d02ed18d824e9799c0327641` |
| `M` | `backend/app/ai_assistant.py` | 23968 | `03f55ee592e58ca129096c32b6e025680f9615d8eb9fb6cb7e5123d68cd8b432` |
| `M` | `backend/app/main.py` | 53299 | `394fdeb16e0f43814b8e1c159d8f32b8b0af61b24d1f0c4960cf3cb07c4910ea` |
| `M` | `backend/app/model_calls.py` | 15074 | `c78777616a9a49964847d3742f0c6983a96defcd2edbcef4dc5851613413704e` |
| `A` | `backend/app/model_service.py` | 19902 | `6114c3016564c75133150208ffb7b174ee5d68864797a4b3006b5ff959fbc189` |
| `M` | `backend/app/models.py` | 12031 | `49af9872fb0d44cdb85e28feac1b89c240d280768fbef5b090b90eae4db3152d` |
| `M` | `backend/app/providers.py` | 11476 | `188978c35ecec091d4c74988a18df495a5f35b4a8050736a24a3e9be785f3398` |
| `M` | `backend/app/schema_cli.py` | 3475 | `35e9bc29f0cc24041522c29e349b978450f6ac5076840c6f908eea1a9a7c73ba` |
| `A` | `backend/tests/test_model_service_settings.py` | 23276 | `0984015f54458217b591e8c16b874019c09f445ab19df25e2435234a02f4bea6` |
| `A` | `docs/MODEL_SERVICE_SETTINGS.md` | 9055 | `780635852f3726a1b5bf528611923fc36d541157f5f11901d10df749862f0490` |
| `A` | `docs/P1_INDEPENDENT_RUN_REPORT.md` | 7836 | `bae12fa228752d376666a8391c5f1c0b6dec7deb22313dab7e07e4089580699a` |
| `A` | `docs/P1_MODEL_SETTINGS_REPORT.md` | 11515 | `76eb39466b5f85032382d0aeceda6d32e504597c652a8004d7af688c3ea1c045` |
| `A` | `docs/P1_REVIEW_ROUND1_REPORT.md` | 5367 | `64b17bf1a83db61d8917228c195a1c57f56b645a770fa8d30f3c6609f1e7059a` |
| `A` | `docs/P1_REVIEW_ROUND2_REPORT.md` | 6049 | `f4f543fe4270ce122c8ea70a9a0eda39e2e14eb5cae10614dce0f883a0416ef6` |
| `A` | `docs/P1_REVIEW_ROUND3_REPORT.md` | 3461 | `a5555087fd2c0d9f528c94f6adac4a2632ada16a4e7eacfea7af830029636514` |
| `A` | `docs/P1_REVIEW_ROUND4_REPORT.md` | 3506 | `77971a54dc661158d77acbc46474ed4f6700f7e928e5b532df6ede5fd68dee77` |
| `A` | `docs/P1_REVIEW_ROUND5_REPORT.md` | 2891 | `fd743f003523a23596782b5d7cbb93745dd1b48a20db44129bf74ebf3678ead9` |
| `M` | `docs/contracts.json` | 80438 | `05474cfc76f5d829cf87ed4f1256180366141ac24b8d6270ae89dad92ac3d911` |
| `M` | `docs/openapi.json` | 94882 | `25535de876cae85565c9052e590b096c852b77cc5d2ce1baa407942dd33f7b48` |
| `M` | `frontend/playwright.ai.config.ts` | 1783 | `95f19e284f1ddce206f76a81c580d1cfc7aac127ac5318573c1d41079c5de6cc` |
| `A` | `frontend/scripts/capture-p1-screenshots.mjs` | 2542 | `027c96f732ba7e13b928607994f1c15296a9b86e514030ed1bdb6536ae46e59e` |
| `M` | `frontend/src/App.vue` | 54031 | `d6a1ec9afc56af216e6130faf61fe25c64f408be1d474a4a3e0b627f96019478` |
| `A` | `frontend/src/components/settings/ModelServiceSettings.vue` | 12668 | `6d339c70d1cb02c345be79fa27e4e8ca25b132f02e8cefa5c93186598ba2dbd2` |
| `A` | `frontend/src/model-settings.ts` | 3308 | `997da25c717f481821517bffc9d757bc68b72a6f839d85e1a2b226984704853e` |
| `M` | `frontend/src/style.css` | 10396 | `77c2c082d8be9623d8deb451c74f1d4f047ce439ce95dc2475a9b477086e7cd2` |
| `A` | `frontend/tests/model-settings.spec.ts` | 8755 | `5b5fd88247d2b62afbec59ba40792a14b9c79d783ace883968a5dce4e870447e` |
| `A` | `frontend/tests/model-settings.test.mjs` | 3718 | `5a4480812175ee522d169777394059eb46f92d6fd49f45e8fa49bbf8c5aa82c1` |
| `A` | `frontend/vite.p1.config.ts` | 475 | `d020d69e8441e1e3bca9bb2be1fbe96d09dafc490921e89c55bdc58754be3aaf` |
| `A` | `scripts/p1-common.ps1` | 17761 | `61f80b3b97d7c836bf5db82c335a507fa3e0eb70a659e5e7e69a5cd90dc75dc4` |
| `A` | `scripts/p1-start.ps1` | 18388 | `8c649e670bf01f22a8cf829fbf16a84e97627574dc5594229c486d555773bd23` |
| `A` | `scripts/p1-stop.ps1` | 6119 | `faaf2d84b4603a409bee9c42f5f49fa08d91402c75acec3143722eb0814c4d10` |
| `A` | `scripts/verify-p1-datadir.ps1` | 3648 | `15d9a5921b3fd1a5b8ebb153605b88e102b3e92e4e653a0be25ad25cabfb726d` |
| `A` | `scripts/verify-p1-guards.ps1` | 7536 | `4578dc37452ca4d930a93a02875ded0a2533dfa48406bf3e8f875d164503c74c` |
| `A` | `scripts/verify-p1-process-identity.ps1` | 3195 | `68bd68b4644fb1598926493ddecb1ab686702fbeb0d645b28a7d0d5cd6a17ce2` |
| `A` | `scripts/verify-p1-r3-startup.ps1` | 5183 | `781e0747a42b1d581deeeb637685c7373467c85caaffc63b73587448828cc953` |
| `A` | `scripts/verify-p1-r4-startup.ps1` | 8670 | `8868b0914c949035af0b75a3d9876982cef746e2b8f7effe5cb84528a8aa1480` |
| `A` | `scripts/verify-p1-r5-identity.ps1` | 9002 | `41a3b5a47faa259c44f4a999335c138aeae872bd90ba1e2fcac70ab19d2110d7` |
| `A` | `scripts/verify-p1-rundir.ps1` | 3219 | `e323f6b395998d3ef0daed83729e6a4db1c12b1734cf79f123eb74067f0e313e` |
| `A` | `scripts/verify-p1-runfile.ps1` | 4651 | `96ec7c7a8672f4061b4cbe6791c3b4c6c9d3b372f191cb02397ad441d7277dfe` |
| `A` | `scripts/verify-p1-start-cleanup.ps1` | 7168 | `137e1d1db382add1a1cc11e46beca67d6e7452d89d24aed28b669c0cfcce6a73` |

合计：41 个修改/新增文件（不含本清单自身）。
