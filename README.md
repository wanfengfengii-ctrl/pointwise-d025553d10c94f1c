# 三工位轮廓复测台账

轮廓试验室的站员登记试片标记，计量员以指定观测修订发行重叠件。分析员下午用三份来件核定 B、C 两个探点在 A 系下的联合落点。复测班领取成对坐标和出处，遇到无共同配准时安排补测。勘误增加新修订，原单、原件及历史报告仍可按原身份核对。

## 运行

需要 Python 3.11，使用标准库。完整正常回归使用控制台提供的项目入口。

```sh
python3 -B check_project.py
python3 -B demo.py --case all
```

`demo.py` 的 `--case` 也可取 `rotated` 或 `symmetric`。演示从 `samples/` 读取有限样例，在临时目录中使用实际 SQLite 库。旋转样例另做一次勘误并重开中心库领取新旧定稿。

遮挡后的局部重叠（V2）由运行清单的统一入口核验与演示：

```sh
python3 -B run_verification.py   # 原回归 + V1 遮挡对照 + V2 共同基准核验
python3 -B demo_partial.py       # 遮挡对照、停站签发、混件拒办、勘误与按号复领
```

V2 的调用契约以 `PARTIAL.md` 为准：`overlap.issue.open_partial` 固定同批
A/B/C 各一个冻结修订，`freeze_partial` 分边发行只读本边两侧原测，
`export_partial_links` 在边件已自证时返回空元组；中心侧
`report.publication.publish_partial` 验件、按双标记三元组门槛核定闭环并一次
写成报告与回执，`report.history.get_partial`、`report.export.export_partial`
按正式号复领。原 V1 接口、件字节、历史和回归保持不变。

## 一天的工作

1. 打开站库和中心库并初始化。重开时继续使用原记录。
2. 站员按批和工位登记每份完整分类标记表，收到修订号。
3. 计量员为 AB、AC、BC 各选两个确切修订，发行可独立移交的件。
4. 分析员登记实收三件及分别属于 B、C 的探点，取得固定复核单。
5. 停站后分析员取固定单与原三件核定共同配准和联合落点。
6. 分析员签发，中心一次提交报告与对应回执。
7. 晚到勘误追加修订。受影响的边可选新修订重发，再以新选择登记另一张单。
8. 换班后按正式报告号领取原结果与原回执。

## Python 接口

`database.open_database(path)` 是关闭连接的上下文管理器，启用 SQLite 外键。用其连接构造 `survey.store.ObservationStore` 并调用 `initialize()`。中心库在同一连接上构造 `review.store.OrderStore` 和 `report.store.ReportStore`，依次初始化。在这些连接上由业务入口管理写事务。初始化与样例录入分别调用。

| 模块和接口 | 输入与返回 |
| --- | --- |
| `survey.intake.record(store, batch, station, markers)` | 登记完整标记表，返回正整数修订号。标记项形如 `{"category":"蓝","point":["1/2",0]}`。 |
| `survey.corrections.amend(store, revision_id, replacements)` | 以明确原修订为基准同时应用一项或多项替换。每项形如 `{"at":[0,0],"category":"蓝","point":[1,0]}`。`at` 指旧位置，每个旧位置至多替换一次。返回新修订号。 |
| `survey.revisions.get_revision(store, revision_id)` | 读取原测快照及其可选父修订号。 |
| `overlap.issue.freeze(store, role, source_revision, target_revision)` | 返回不可变有向件。AB、AC、BC 分别要求 B→A、C→A、C→B。两侧修订同批。同一工位可以在不同边上选择不同修订。 |
| `overlap.exchange.export_evidence(piece)`、`verify_evidence(text)` | 在不可变有向件与 V1 JSON 文本之间交换。相同修订选择和正文有相同内容身份。来源不同的件即使变换相同，也不同号。 |
| `review.intake.order(store, pieces, named_points)` | 接收任意输入顺序的三份件文本和 `{"B":[x,y],"C":[x,y]}`，返回固定 `ReviewOrder`。以 `store.read_order(id)` 可按号读回。 |
| `analysis.execute.evaluate(review_order, pieces)` | 仅使用固定单和实收三件，返回 `ReviewOutcome`。|
| `report.publication.publish(store, outcome)` | 用该中心库的原单核对结果、出处和探点，提交后返回带正式号及回执的 `ReportSnapshot`。接收 `evaluate` 产生的结论，每次成功签发产生一个新报告号。 |
| `report.history.get(store, report_id)`、`report.export.export_report(store, report_id)` | 返回存档快照，或导出同一快照的 JSON 文本。 |

批名及类别是非空、首尾无空白的可打印字符串。工位为 `A`、`B` 或 `C`。坐标单位为毫米，Python 数据可用 `int`、`Fraction` 或 Python 3.11 `Fraction` 可解析的有理字符串。JSON 样例用整数和字符串。浮点数及布尔值拒绝。每份标记表至少含两个不同位置，同侧任意两项在有理规范化后位置相同即拒绝。

## 核定口径

件内变换 `[c,s,tx,ty]` 将源坐标 `(x,y)` 送到 `(c*x-s*y+tx,s*x+c*y+ty)`，要求 `c²+s²=1`。同类标记共享类别，发行计算按各类点集精确映合，保留对称产生的全部合法变换。V1 JSON 外层为 `version`、`ref`、`body`。`ref` 记录批次、有向角色、确切源和目标修订、件身份及正文 SHA-256。`body.transforms` 是按变换参数数值顺序保存的不同变换，参数为规范有理字符串。摘要校验覆盖规范正文，件身份还绑定外层出处字段。交换完整性校验以内容和固定绑定为依据。原标记表留在站库。

有共同配准要求同一组 B、C 到 A 的位姿同时满足三边。AB 与 BC 的复合先将 C 系送入 B 系，再送入 A 系，其结果必须属于 AC 件。先判闭环资格，再运输探点。结果用 `aligned` 或 `no_common_registration` 表示，落点以 `((B.x,B.y),(C.x,C.y))` 为一对，按四个有理坐标的数值字典序去重并排序。报告 JSON 将坐标保存为精确有理字符串。合法空件与闭环冲突均可正式签发 `no_common_registration`，其落点为空。多个合格位姿投影到同一对坐标时，签发 `aligned` 和一对落点。相同输入的计算和编码均为确定性的。

输入、来源、角色、实收绑定或发布绑定非法时抛出 `ValueError`。未知修订、复核单或报告号抛出 `LookupError`。SQLite 写入或提交错误向调用者传播并回滚该次操作。领取按正式号读取存档正文及同次回执。站库和实收件在领取时均可离线。

## 独立核对样例

- 旋转样例中 AB 将 B 系先逆时针旋转 90° 再平移 `(1,0)`，BC 将 C 系沿 B 系横轴平移 `(1,0)`。所以两个局部原点应落在 `(1,0)` 和 `(1,1)`。B 探点换为 `(1/2,0)`、C 探点换为 `(1/3,0)` 时，落点应为 `(1,1/2)` 和 `(1,4/3)`。
- 对称样例中 AB、AC 均支持原向和半转，BC 只支持半转。两个 `(1,0)` 探点在 A 系应得到 `((-1,0),(1,0))` 和 `((1,0),(-1,0))`。两探点换为原点后，两组合法位姿只产生一对原点。
- 完整回归覆盖私有原据、重复位置、空件、件格式、替换来件、错批、方向与角色、闭环与投影、事务提交失败、勘误、重复初始化及历史回执。
