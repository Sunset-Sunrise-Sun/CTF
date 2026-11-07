# stream-content-v1 Golden KAT — KAT-FINAL

当前结构边界修订基线：0c34e60fcaae8d8156aa906ed571d0d9ffc0578c；原 Golden 冻结基线：3239fac2d5cbafc3e69b4553653f64045ac15546。本轮在独立分支 fix/kat-json-structure-limits 修订离线参考实现；stacked Draft PR 目标为 PR #3 分支，不修改 main 或 PR #1/#2。

## 冻结范围与文件

本报告将基线 §8.1.1.e 中尚待完成的 KAT 参考向量冻结为 fixture；不改变 stream-content-v1 算法、V1 输入或生产能力。旧设计/收敛记录保留为历史。本次通过仅指下列独立参考脚本，不代表 Python 生产实现、接收器或执行器通过。

- tests/fixtures/stream_content_v1_kat.json：固定 synthetic key、所有原始输入 UTF-8 hex、固定 expected。
- scripts/kat/stream_content_v1.py：Python 独立参考解析、Canonical、framing、HMAC 与只读测试 runner。
- scripts/kat/stream_content_v1.mjs：Node.js 独立 token-aware JSON parser、手写 Canonical、framing 与 crypto HMAC runner。
- scripts/kat/compare_reports.py：比较两份实际结果和固定 fixture；不生成 expected。
- docs/STREAM_CONTENT_V1_KAT_FINAL.md：本报告、矩阵和复现命令。
- docs/STREAM_CONTENT_V1_KAT_SHA256SUMS：fixture 与三个脚本的 SHA-256。

公开 synthetic key：`000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f`。固定测试字节，非真实密钥；**禁止用于生产**，不读取 Provider 环境变量或本地 keyring。

## V1–V3 固定 MAC 与完整字节

fixture 每条 full 向量的 expected 均保存 J_C_hex、R_hex（逐记录）、展开后的 M、J_M_hex、每个 F 项的 length/prefix_hex/framed_hex、完整 content_message_hex/batch_message_hex，以及两层完整 64 位 hex MAC。没有省略号、运行时拼接的 expected 或只比较摘要的替代品。

| 向量 | content_fingerprint | batch_digest |
|---|---|---|
| V1 | `3f57d082c5c48a274da05be826512e78ba69022f726e2944c17edc864d3bb4be` | `3c5b4eddd1dc7d8e5a706a51a2b2c34192f9dfb82ae0e225d5272187a4bc4353` |
| V2 | `6eb4f5c21a60752172c31d5f12406097745a8f44beaf427e225821e92726ad1c` | `184636adc641086fdcc1b8d2b3331ac58d18add5683a2d73e74111a11f9beda1` |
| V3 | `1eb38a23e50cd057323999f0c62957d8a7c2271d54e513d42f2c36a8560b50b2` | `ed42d756080b00dbad1f573e3c8025079d2c657a48051f74eb982f2063607c4f` |

V1 的 J(C)、R_1、J(M)、两完整 framing 消息及两个 MAC 均与指定基线逐字节锚定，未重新定义输入。V2 原 function.arguments 为字符串 `{"n":1.0}`，MAC 前不解析或重序列化其正文。V3 保留 quote、反斜杠、NUL、BS/TAB/LF/FF/CR、U+2028/U+2029、U+1F600，内容 UTF-8 长度 18。

## K02–K11 矩阵

| 分组 | 固定内容 | 正向 / 精确拒绝 |
|---|---|---|
| K01 | V1 完整向量：双库 Canonical、F 消息与两 MAC | 1 / 0 |
| K02 | 11 个数字字段的 float/exponent/string/bool/null/-0/负数/越界与正整数零；NaN/Infinity/-Infinity | 0 / 98 |
| K03 | 同一工具向量 content 缺失/null；非法 name/arguments null | 2 / 2 |
| K04 | V3 控制/非 BMP、中文英文、NFC/NFD、scalar 键序、合法等价 escape、非法 UTF-8/surrogate/BOM | 6 / 5 |
| K05 | 逆序对象键；工具数组 AB/BA；AB 单块与 A/B 两块 | 5 / 0 |
| K06 | choice 转义等价重复键、function 嵌套重复、C 重复字段 | 0 / 3 |
| K07 | 中A 与文A 同长不同字节 | 1 / 0 |
| K08 | 不同 batch_id；supplied_M 只改上下文的唯一 context_mismatch | 1 / 1 |
| K09 | 固定 V1 重新输入；两个 runner 还分别启动 V1/V2/V3 各两个新进程 | 1 / 0 |
| K10 | 固定六位 UTC、闰年/年1合法；省略/毫秒/Z/偏移/-00/闰秒/非法日期/纳秒拒绝 | 3 / 8 |
| K11 | V2 原始 arguments 字符串；正/非负/索引 min/max 字段单元；tool.id UTF-8 256/257 bytes、标识/name 上限、choices/delta 帧数量 | 28 / 7 |

原 172 条（48 正向、124 负向）完整保留，另追加 23 条结构边界用例（8 正向、15 负向），合计 195 条（56 正向、139 负向）。负向 expected 固定为完整 `{status,error code,可选 limit_code}`，实际输出必须完全相等；不接受“抛任何异常即可”或候选错误码集合。原 negative 维持原输入；新增组合违规用例按下文固定的结构预检优先级冻结。

三种 fixture mode：full 验证批投影并计算完整 MAC；field 隔离类型/范围/格式，防止一个非法数值又引发区间/计数等次生错误；canonical 隔离 JSON 词法、Unicode 与键序。后两者 expected 是固定 canonical hex 或唯一错误码，不假称完成批的 HMAC。SAFE_MAX 字段单元通过不表示该值满足真实请求限额。

时间格式单元的格式错误统一 timestamp_format（含超出固定32字节格式的九位小数）；变量标识超过其 UTF-8 预算返回 limit_exceeded/string_utf8_bytes。两组测试分别隔离格式与预算，不依赖未规定的跨阶段错误优先级。

## 独立计算和冻结方法

先从基线提取固定输入，以两个独立脚本离线计算 actual；比对每个字段及手工指定的 negative code，再将一致的结果写入 golden fixture。V1 所有固定 hex 与基线比较，V2/V3 MAC 也与既有摘要一致。一次性的输入/冻结工作脚本不作为测试程序提交。

测试 runner 默认要求 kind=golden，只读取 expected；没有更新 fixture 的测试开关。--calculate-only 只接受 kind=unfrozen-inputs，输出候选 actual 并明确标 NOT a test run，拒绝用 golden 重新生成预期；--report 不允许覆盖 fixture。冻结后实际测试与比较只读取固定 expected。

Python 在 stdlib json 构造对象之前新增有界迭代结构预检，之后仍保留原数字 token/重复键检查；Node 在独立递归解析器之前同样新增独立迭代结构预检，递归解析器（JSON.parse 仅用于单个字符串 token），自定义 scalar 键序和逐字符转义，避免整对象 JSON.parse 丢失重复键/1.0 的证据。两套实现没有互相 import 或运行对方来计算字节。HMAC 分别用 Python hmac/hashlib 与 Node crypto。

## 复现命令（仓库根目录；只用语言标准库）

```text
python scripts/kat/stream_content_v1.py --fixture tests/fixtures/stream_content_v1_kat.json --report python-actual.json
node scripts/kat/stream_content_v1.mjs --fixture tests/fixtures/stream_content_v1_kat.json --report node-actual.json
python scripts/kat/compare_reports.py --fixture tests/fixtures/stream_content_v1_kat.json --python python-actual.json --node node-actual.json
```

actual 报告建议写到工作目录或 work/ 下，不提交到 Git；脚本仅写用户明确指定的 --report 文件。

## 实际测试输出（Windows，Python 3.14.7、Node.js v24.19.0）

```text
Python: 195 frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS
Node.js: 195 frozen cases PASS; 6 fresh-process V1/V2/V3 checks PASS
Cross-language: 195 exact frozen results PASS (56 positive, 139 exact error-code cases)
Canonical/framing/message hex and both MACs: byte-for-byte equal
fixture_sha256=92a790c122f0f60a56a60b12ee5d36e77bfdb2a379f65f46cf7f9c291d7c0bd6
```

每个 runner 的6次新进程（每向量2次）均重新读取固定 fixture 并比较 expected。比较器还确认两份标准化 UTF-8/LF 实际报告的完整文件字节相同。Ruff 对 Python 参考脚本检查通过；未运行生产项目测试。

## 完整性与未完成事项

fixture SHA-256：`92a790c122f0f60a56a60b12ee5d36e77bfdb2a379f65f46cf7f9c291d7c0bd6`。所有交付文件 UTF-8/LF，SHA256SUMS 记录 fixture 和三个脚本的文件字节校验值。最终提交 SHA 通过 PR 提交记录/交付消息提供（不能把 commit 自身 SHA 自引用写入其内容）。

未完成且不属于本轮通过范围：生产 Provider stream 接收器、token/Canonical 流式预检、HTTP/SSE 入口预算、跨批请求累计和重试持久化、keyring/轮换恢复、数据库/事件链、工具执行与 Writeup。参考脚本读取有界离线 fixture 后计算，不是流式内存/DoS 防护实现，也不证明 R5 全部场景已通过。仅 K02–K11 明列的类型/字节边界样例执行，不宣称执行了设计的全部 S07/R5 状态故障矩阵。

未调用模型、未生成真实审计密钥、未修改 SQL/附件/生产执行代码；不改 main、PR #1/#2、不合并 PR #3。冻结产物仍待独立复审。


## JSON 结构资源边界修订

### 执行检查的位置与定义

- 容器深度硬上限 8：object/array 均占一层，root 容器=1，primitive 不增加深度，兄弟节点不累积深度。进入 `{`/`[` 前检查即将进入的层数，第9层在压栈之前拒绝；深度8允许。
- 每对象最多16个成员键：逐对象独立计数，开始读取成员 key 的双引号时预留成员配额，第17个在读取完整 key/其 value 之前拒绝；16允许。计数包括重复成员出现次数，不按 distinct key 去重；允许范围内的重复键仍由后续解析器报 duplicate_key。
- 预检是非递归扫描，自己只维护至多8帧的扫描栈和字符串/escape 状态；字符串内部的括号、逗号、转义引号及 Unicode escape 不当作容器或成员。两边都在递归 parser 构造输入 object/list 之前执行，不靠 Runtime 栈溢出，Python 不再捕获 RecursionError 来伪装资源拒绝。
- 限制作用于每条 case.input_utf8_hex 解码后的完整 JSON 输入，full 模式连同 C/records/M_extra wrapper 一起 root=1（V2 原 wrapper 最深为8，仍通过）；不是对包含195条记录的受信 Golden fixture 文件施加16键限制。
- 本轮仍是离线参考实现，UTF-8 解码及输入文本缓冲已经存在；新增的是对象递归构造前的结构检查，不声称实现了生产网络流式解码器。

### 统一错误与固定优先级

两种结构拒绝都使用 `code=limit_exceeded`、`limit_code=projection_structure`，并增加精确可观察的 `structure_limit`：深度为 container_depth，成员数为 object_keys。原有172条结果不新增此字段，原 expected 完全不变。结构负向 expected 比较 status 与三个错误字段，不接受任意异常或候选码。

优先级固定如下：

1. 原有 BOM/严格 UTF-8 校验。
2. 非递归结构预检，按原始源文本从左至右。进入新容器前检查深度；看到成员 key 起始引号前检查成员数；第17个 key 的检查一定先于其 value 的深度检查。预检还拒绝不匹配的容器结束符。
3. 只有结构预检通过才做完整 JSON 词法、数字 token、字符串和重复键检查，随后执行语义/schema 校验与 Canonical/HMAC。因此结构超限与重复键同时存在时，即使较早出现重复键，预检阶段仍先拒绝其发现的结构超限；未超结构限额的重复键继续报 duplicate_key。

这不是“深度永远高于键数”：若第17个 key 先出现就 object_keys；若较早的子树先进入第9层就 container_depth。只返回首个确定拒绝，不读取完整超限对象，也不继续找其他错误来覆盖它。

### 追加23条固定用例

| 类型 | 新增数量 | 预期 |
|---|---:|---|
| object/array/mixed 深度8与9 | 6 | 各8通过、9 container_depth |
| root/nested 对象16与17键 | 4 | 各16通过、17 object_keys |
| 深度8处16与17键 | 2 | 16通过、17 object_keys |
| 结构组合违规优先级 | 4 | key17先于深值、深值先于后续key17、depth9对象含17键、depth8的key17值再depth9；按源位置固定赢家 |
| 字符串中的伪结构、转义key16与17 | 3 | 字符串不计容器；转义key16通过、17 object_keys |
| 预算内重复键及结构/重复键组合 | 3 | 分别 duplicate_key、object_keys、container_depth |
| 10000层数组 | 1 | 在第9层 container_depth，不能等到运行时栈溢出 |

新增 positive 的 canonical hex 由固定、已规范排列的文本直接写入，negative 的 code/limit_code/structure_limit 逐例固定；不运行脚本生成旧 expected。Golden 测试依旧只读所有固定 expected。

### 旧172条保留证据

将新 fixture 前172条的完整 case（含原始输入、mode/group/id 和全部 expected）与基线逐对象比较，完全一致；再用两个 actual 报告逐条对比基线 expected：

```text
Original 172: complete inputs and expected unchanged; Python/Node actual PASS
Original case-list canonical SHA256: aba45523e3c180e5f07e599dc4bb9b021fefec70e7de28c34ad5349b48b9d0a2
```

该 SHA 使用 UTF-8(json.dumps(original_cases,sort_keys=True,ensure_ascii=True,separators=(',',':'))) 计算，仅用于证明原 case 集合未改，不是重算/替换协议 expected。旧整份 fixture SHA 为 55e5cbd6f9cecf1b48bf2507c6f2e56cb7ad1a99eca2ec92707af6dc4dca5e77；新整份 fixture 因追加用例而正常变化，见当前报告/SHA256SUMS。

### 本次变更文件与边界

1. scripts/kat/stream_content_v1.py：迭代结构预检、结构拒绝细分；不依赖 json object_pairs_hook 事后限制深度/成员。
2. scripts/kat/stream_content_v1.mjs：独立迭代结构预检及一致错误字段。
3. tests/fixtures/stream_content_v1_kat.json：只追加23条 case，保留旧172条输入和 expected。
4. docs/STREAM_CONTENT_V1_KAT_FINAL.md：新边界、优先级、实际195条输出及回归证据。
5. docs/STREAM_CONTENT_V1_KAT_SHA256SUMS：更新 fixture/两个 runner 校验值；比较脚本未改。

实际完整测试195条、跨语言逐字节比较和各6次新进程检查均通过；Ruff 检查通过。未修改/测试生产工具、模型服务、数据库、附件或 keyring；没有真实审计密钥或网络调用。独立分支 Draft PR 等待审核，不合并。
