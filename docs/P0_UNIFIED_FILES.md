# P0 统一整合修改文件清单

- 分支：`feat/p0-unified-ai-tools`
- 基准 HEAD：`30eeed6dcc180ae21b5648f25047c5889e3c434a`
- 说明：列表为 `git status` 中相对基准的修改/新增文件（排除 `node_modules`、`dist`、缓存、`verification/evidence` 二进制证据）；SHA-256 为当前工作树字节。
- 完整 diff：`verification/unified-p0.diff`；校验和清单：`docs/P0_UNIFIED_SHA256SUMS`。

| 状态 | 文件 | 大小 | SHA-256 |
|---|---|---|---|
| `??` | `P0-UNIFIED-DELIVERY.md` | 6894 | `c53d32e9bfdf273c0254de00a67f96a2708c2cd3ab234e1f52290483f42ac43e` |
| `M` | `README.md` | 3672 | `4674d7945dab9cadf46ae91076ff9283548c820471aec3c58ea222e74e75e5b9` |
| `M` | `backend/app/ai_assistant.py` | 22055 | `f102e3f59ed528c4543f8c8d5cc50da43842cefd87054d3b20ac58064d2c97ed` |
| `??` | `backend/app/ai_policy.py` | 2271 | `fae65e11baf2199d651fa6584b4dec421aee0234aabad2975db4f67fcfdd4260` |
| `M` | `backend/app/ai_smoke_cli.py` | 3178 | `36058b7b786ba6e424a7b82b4de1b88cdcc2c558f28ab97f6e62966971b32e55` |
| `M` | `backend/app/export.py` | 28770 | `6302af966a3ccf4a4e4143569a04ac0b579779361ace4b328262d8ed0897ae05` |
| `M` | `backend/app/main.py` | 50361 | `77e4e6f5b3ba33443232c0becfa1abbd59c2a83f79a1133948edb50086dc30f0` |
| `??` | `backend/app/migrations/003_tool_approvals.sql` | 2258 | `abab80dbcc13e9be261dbac2de0c42d99ff7eaf14fc23d2fbe349da62c11cc9a` |
| `??` | `backend/app/model_calls.py` | 14517 | `3518bdd824a1fe1641b66dad0a1217d1e24c3aea4c26ae002121bde0c10c9974` |
| `M` | `backend/app/model_cli.py` | 1029 | `02f5db177c58f0839fe971b5f25a7e90860901701a7f799653940d8ea06f7fa5` |
| `M` | `backend/app/models.py` | 10942 | `3fc7313530ecf39b50bf15cca0534022654b7afd31013cca0f63e366f0d2e141` |
| `M` | `backend/app/providers.py` | 11000 | `109ba35ff564516ccf886c66e7d60d1b6a804407db601efad37521c0eb60a270` |
| `M` | `backend/app/schema_cli.py` | 3317 | `46cca8f63b6cc305be7a694958eaa14c7d538ef0b1f104f6053c05380e3ab6a2` |
| `M` | `backend/app/store.py` | 16803 | `aad6b8d41e92ad54225440ae095333127b92f8fc7a0b9a67b9d18304d64a24eb` |
| `??` | `backend/app/tool_impl.py` | 12764 | `327cc1b277154ae324562411482b2e0a16a8c062a94c6670bf03ae1a3172a12d` |
| `??` | `backend/app/tool_registry.py` | 5767 | `40ecdb6d19dfa8b8b95064ea175a44c1b71d310d983dd25b0bcfe852dca03577` |
| `??` | `backend/app/tool_runner.py` | 2502 | `f6381384df9fe4dd160d42d18ff7dc3013d5e54d96285f8d35fed521ef316032` |
| `??` | `backend/app/tool_system.py` | 43936 | `02b09bb814aa01520990aa508b070663b7d21fef4fc5d0bdb9dd1085e146e3c4` |
| `M` | `backend/app/writeup.py` | 39615 | `b31796e45437229ff55e2bbaa2f8d6b4201c5f7cb1beab841cee487c5d49e8d4` |
| `M` | `backend/tests/test_ai_assistant.py` | 16685 | `05a748963728672456edddffad864d13cea11246bae184d41e199604e107a174` |
| `??` | `backend/tests/test_ai_p0.py` | 21823 | `b652e69a509decdb88ac712731f4f9b51b91606db7fc3bee54bfc6950579dd8f` |
| `M` | `backend/tests/test_artifacts.py` | 54581 | `3fdfde41b358056a9f04210f5b450fde92f78e8085ee5784970f4bdb846c02b9` |
| `M` | `backend/tests/test_core.py` | 4755 | `e698ef51083e2b72ff07e62764af5123e5f60a5cda8f7f589af8aecf836f3cb2` |
| `M` | `backend/tests/test_model_audit.py` | 6734 | `9bbc1ebdc523254d0eed10c75d0d8408ad0bd477cd962d1f5addc23e15af850a` |
| `??` | `backend/tests/test_model_call_paths.py` | 3514 | `69c457a9a6c8ac7e2dafb040ccff03e9db71a28364f8a6c4fb1675a3102b6d30` |
| `M` | `backend/tests/test_mvp_writeup_export.py` | 34586 | `95b01941026e5ea581e2ee0435f9fd6151cb0edd111644ba827fa0d63307010d` |
| `M` | `backend/tests/test_providers.py` | 5136 | `916e93d9574961d0ae866481d3a82a7aa789160a69d25225ee5decd30b8ab4f0` |
| `??` | `backend/tests/test_schema_contracts.py` | 1059 | `ef30756f0b21d9f63dedc655f7a953547cbc7203ff337da71de3797924e661ec` |
| `??` | `backend/tests/test_tools.py` | 38600 | `de222308de77de766991e031bd43f0075fd7cc1f10662f0780d22f1531a46b8a` |
| `??` | `backend/tests/test_unified_disclosure.py` | 37403 | `46b8b507cd503594b6b7bd5e0afbf3b4968180449dfe9702acc45bf6ac135a4b` |
| `??` | `backend/tests/test_unified_p0.py` | 11980 | `ab4cb47091adc1eef763acfacea535c5ff1995938296197e03f7fd9ddf9037c5` |
| `M` | `docs/AI_ASSISTED_SOLVING.md` | 9182 | `43c76ee11fa5d274d526844e3595bcd0da530b84a33bc54934c92dc135962359` |
| `??` | `docs/AI_COORDINATION_REPORT.md` | 8029 | `f6e4b28cede518f1bbb86231bb9c0fe623a9771b48824f4d630dd783b7afd1d8` |
| `??` | `docs/AI_P0_REPORT.md` | 5254 | `8954cb09c65b3fa53b2b0848f8ff27aad23c0a52eb02d883c2c4a60d97fc537f` |
| `??` | `docs/AI_PERMISSION_CONTRACT.md` | 3190 | `ebb4a1f32b551869df3829211405fdc908a65b2b70985943258ca97022a8372e` |
| `??` | `docs/FRONTEND_AUDIT.md` | 8152 | `23104442182056904f60907503ac5884e093429e94eaf6aa69da96f17f1e4872` |
| `M` | `docs/MODEL_PROVIDERS.md` | 3920 | `d602cd7f973c6342a564bf1572c100e5f9e0a4a9d063ae00eae7609cd53d9d01` |
| `??` | `docs/NEXT_STAGE_TASKS.md` | 6539 | `dacda117e5fc141f6b556fb82eaa140ed89e6ba4fbd784cf9d1591f598625acb` |
| `??` | `docs/P0_UNIFIED_ARCHITECTURE.md` | 14233 | `522d7b75402193da31bc76bc095dd05bbd8ddc2d5c3c0a8942e64398578131fc` |
| `??` | `docs/P0_UNIFIED_DESIGN.md` | 8696 | `c12c4c3415377299aa3ccfcdd12d775cd0951641b54d65f88977c68648e5a71f` |
| `??` | `docs/P0_UNIFIED_OPEN_ISSUES.md` | 4316 | `9bb903a91aad8444105766a8cdb4cac79994e1b90a0dcc540214674e94f0771b` |
| `??` | `docs/P0_UNIFIED_SECURITY_REPORT.md` | 6088 | `f036da3a099ed3535a5cd5c845d394469574d454271bb8f87c8b9ed91df888f6` |
| `??` | `docs/P0_UNIFIED_TEST_REPORT.md` | 8374 | `bc0a449fd4efad0d43348f15990a9ba41c4105e9d8c56ea7d5421ae87b399026` |
| `??` | `docs/P0_UNIFIED_TOOL_CLOSURE.md` | 4906 | `7a5e9866314fd03b5707abe225aa89a9e4750d226f625e6cc29a71805af78b89` |
| `M` | `docs/contracts.json` | 76360 | `8e7076b5ac0610d2f7f193fe6d2f7d154b9878be9ce72dad505a2be4217e49a6` |
| `M` | `docs/openapi.json` | 87745 | `ea270f27d1d0dbbfb2d8232f3dbff909b7fdb36b334663a6ccf2e6527a721da0` |
| `M` | `frontend/playwright.ai.config.ts` | 1755 | `bee74e1799dc8dc46b847132e257f65c5720901596b7a401b3e6162f0b145933` |
| `M` | `frontend/src/App.vue` | 53558 | `28390b8cb0f2c61eaf8e490a80932f28bd4ed6cd1d44f9ddc2f826fa37699005` |
| `??` | `frontend/src/ai-consent.ts` | 2655 | `6b956eada47a7965b01901c70da25f2ca1fbfd20b58b7e68185ea323dc1faf56` |
| `??` | `frontend/src/components/ai/ToolApprovalPanel.vue` | 11203 | `e4ff7d6bf2619ee5f92a4d3f4e4458fbd5a5db9bca9a724cd2720183eec07ae6` |
| `M` | `frontend/src/domain.ts` | 8822 | `a0cb83771344d842a4a71081ad4a65be99df24d790033ea4f1f9d1f3de5ee1d2` |
| `M` | `frontend/src/style.css` | 10141 | `012f90f447317183ae17881153667f01b21ad4f2c1cdbb7e80c69dc8d67e8102` |
| `M` | `frontend/tests/ai-assistant.spec.ts` | 33697 | `6eaabea691dd475af22b9cf9f0f70283726765e70605074a6f3639be6c23a7e2` |
| `??` | `frontend/tests/ai-consent.test.mjs` | 2201 | `ec082faece64db5143c13465ceba28c91ddc45592b3618e8145464fdffdd4479` |
| `??` | `frontend/tests/tool-approval.test.mjs` | 6202 | `4a71db044dbe3d45593ac33ac562c046461b724046d880b982ecc8db368bcb94` |
| `??` | `verification/README.md` | 1973 | `0253f28b0b3fc51e1da6aa63a4d7a2cfc58168a3f5b52c870c7cbc7e7c112f77` |
| `??` | `verification/build_manifest.py` | 3309 | `af0e15a6943b02b19987a89fea4552a91dac5b0124c88bd901b4f45932b907b4` |
| `??` | `verification/make_diff.py` | 1104 | `1fdfed3e437b0932ea1643bd0ecc9565d73c45a0abd0e9996e45e0d468b1aa7b` |
| `??` | `verification/run_fault_injection.py` | 11511 | `c3d8677e3a22a2cb6f6b65fc4f2fd1caaba337eeb46894baee8923031fc74fac` |
| `??` | `verification/run_http_acceptance.py` | 14679 | `8428de289994c1f9d17120a19ee5c568e8b8d939817516937a1139abb36d89dd` |

合计：60 个修改/新增文件。
