# 遮挡后的共同基准

现有 `README.md` 说明站库、中心库、V1 调用和精确坐标口径。局部重叠使用以下新入口。同一次交接固定同批 A、B、C 各一个观测修订。计量员可分别发行三条边，每条边只读取自己的两侧标记。原测坐标、类别和站内标记键留在站库。

## 站端调用

| 接口 | 输入与返回 |
| --- | --- |
| `overlap.issue.open_partial(store, revisions)` | `store` 为已初始化的 `ObservationStore`。`revisions` 是 A、B、C 到确切修订号的字典。返回仅供本站调用的不透明交接句柄。即使三份修订相同，每次开启也建立新的交接。 |
| `overlap.issue.freeze_partial(store, handoff, role)` | 使用该句柄发行一条边，返回 V2 JSON 文本。AB、AC、BC 方向沿用 V1。合法边可以没有候选。 |
| `overlap.issue.export_partial_links(store, handoff, pieces)` | 输入本次拟移交的三份边件文本，返回本次所需的连结 JSON 文本元组。边件已包含全部连结依据时返回空元组。 |

每个候选是至少两对同类标记精确映合所支持的保向刚体变换。保全所有这样的候选及每个候选支持的全部对应。变换沿用 `[c,s,tx,ty]` 和规范有理字符串。不同候选可使用不同的对应。

边件 JSON 对象含 `version`（整数 `2`）、`handoff_id`、`id`、`batch`、`role`、`source_revision`、`target_revision`、`body_sha256` 和 `body`。`body.candidates` 是由对象组成的数组，对象含 `transform` 和 `matches`。每条 `matches` 记录为 `[源端点标识, 目标端点标识]`，端点标识是非空字符串。同边同侧的同一记录在各候选中使用同一端点标识。新开交接时，端点标识与前次隔离。跨边的实际同一性由边件或所附连结材料证明。使用独立连结材料时，它须证明所选边件中端点的同一性并绑定实际来件。连结 JSON 对象含 `version`、`handoff_id`、`id`、`body_sha256` 和 `body`，正文表达留给实现。外层 `id` 须绑定版本、出处和正文摘要，摘要按现有 V1 规范 JSON 的 SHA-256 口径校验。连结材料也遵守原标记留站规则。

## 中心办理与领取

| 接口 | 输入与返回 |
| --- | --- |
| `report.publication.publish_partial(store, pieces, links, named_points)` | `store` 为中心已初始化的 `ReportStore`。`pieces` 为任意顺序的三条边件文本，`links` 为移交的连结文本序列，可为空。`named_points` 沿用 V1 的 `{'B': [x,y], 'C': [x,y]}`。验件、核定并签发，返回存档字典。 |
| `report.history.get_partial(store, report_id)` | 读取已签字典。只须打开中心库。 |
| `report.export.export_partial(store, report_id)` | 返回同一存档字典的 JSON 文本。 |

中心核对三个角色、同一交接、批次和每站确切修订，再核验正文与实际连结材料。有资格的位姿须满足 `AB ∘ BC = AC`。在这三个确切候选的对应关系中，一个标记三元组须同时具备 AB 的 B→A、AC 的 C→A 和 BC 的 C→B 对应。至少有两组不同三元组才采用该位姿。按 V1 数值字典序对 B、C 整对落点排序并去重。有效的空件、无闭环或闭环缺双基准均可正式签空。

存档字典含 `report_id`（正整数）、`handoff_id`、`batch`、`references`（依 AB、AC、BC 的实际 `id`）、`link_references`（实际使用的连结件 `id`，按来件顺序）、`points`（归一后的具名探点）、`status`、`pairs` 和 `receipt`。`status` 为 `aligned` 或 `no_common_registration`，后者的 `pairs` 为空数组。探点及落点坐标均用规范有理字符串，`receipt` 含可复领的 `id` 和对应的 `report_id`。按号读取同次签存的值，站库后续勘误、中心重开均不改旧稿。读取无需任何来件。

坏件、所需连结材料缺失、错角色、混交接、混版或非法参数抛 `ValueError`，合法未知修订号或报告号抛 `LookupError`。SQLite 签存异常向调用方传播。报告和回执一次写成，失败无新增且可重试。原 V1 接口、件字节、历史和回归继续使用。

## 对照样例与运行

`partial_cases.py` 的 `CASE_MARKERS` 提供原测输入，`EXPECTED` 给出用指定探点手算的精确落点。`one_common` 和 `two_common` 的每条边都只支持恒等变换，且各有两对标记。前者仅 u 三边贯通，应签空。后者 u、v 都贯通，签 `((1,0),(0,1))`。`one_witness_qualifies` 有两个闭环位姿，其中半转 B 的位姿仅有一个共同基准。`half_turn` 有两组相反的合格位姿，探点换成两个原点后只留一对落点。

`python3 -B partial_cases.py legacy` 调用原流程展示两组遮挡输入的 V1 结果。实现新接口后，`python3 -B partial_cases.py partial` 走分边发行、停站签发、混件拒办、勘误和重开领报。核验还须覆盖坏件和签存失败后的重试。

沿用 `.pointwise-runtime.json` 的运行约定。`version` 为 1，`kind` 为 `cli`，`setup` 是准备命令的参数数组列表。`verify` 和 `demo` 各是一条命令的参数数组。让 `verify` 执行原回归和本次共同基准核验，任一失败须非零退出。让 `demo` 实际展示遮挡对照、停站签发与按号复领。
