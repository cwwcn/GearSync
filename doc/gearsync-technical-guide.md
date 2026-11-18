# GearSync 技术说明

本文对应 GearSync 当前代码结构，覆盖 Garmin 中国区、Garmin 国际区与 COROS（高驰）的活动同步，以及独立的 RQrun 签到模块。颂拓（Suunto）目前不是 GearSync 的同步端。APK 逆向材料描述的是 GarSync，不能当作 GearSync 与第三方服务之间的正式 API 合同。

## 1. 范围与术语

GearSync 提供三种活动平台：

| 代码名 | 平台 | 账号区域标识 |
| --- | --- | --- |
| `GARMIN_CN` | Garmin 中国区 | `garmin.cn:<profileId>` |
| `GARMIN_GLOBAL` | Garmin 国际区 | `garmin.com:<profileId>` |
| `COROS` | 高驰 | `<regionId>:<userId>` |

每次活动同步有一个来源、一个目标和各自的账号身份。账号身份只用于本地状态隔离；密码、OAuth 凭证不会放入 `scope`。`activity_id` 是来源端活动 ID，`remote_id` 是目标端活动 ID。

支持六个方向：COROS ↔ Garmin 中国区、COROS ↔ Garmin 国际区、Garmin 中国区 ↔ Garmin 国际区。当前不支持 Garmin ↔ Suunto 或 COROS ↔ Suunto。

## 2. 模块结构

| 模块 | 职责 |
| --- | --- |
| `scripts/gear_sync.py` | 通用入口；校验 `SOURCE`、`TARGET` 并分发至固定方向入口 |
| `scripts/*_to_*.py` | 六个固定方向入口；调用统一 CLI，不实现各自的同步循环 |
| `scripts/sync_cli.py` | 读取配置、构造客户端、识别两端账号、取得运行锁、创建状态库并报告退出码 |
| `scripts/sync_engine.py` | 活动扫描、增量检查点、文件流程、持久状态迁移、目标核对和重试控制 |
| `scripts/sync_types.py` | 统一活动、对象上传回执、导入回执及同步错误的数据类型 |
| `scripts/garmin/garmin_client.py` | Garmin 中国区和国际区共用客户端；子类区分域名 |
| `scripts/coros/coros_client.py` | COROS 登录、活动列表和下载、OSS/S3 上传、活动导入及任务查询 |
| `scripts/oss/` | Aliyun OSS 和 AWS S3 分片上传实现 |
| `scripts/activity_files.py` | FIT/ZIP 校验、SHA-256、COROS ZIP 包装和本地原子缓存 |
| `scripts/db/sync_state.py` | `activitySync.db` 同步状态、历史兼容迁移和账号/方向隔离 |
| `scripts/rq_sign.py`、`scripts/rq/` | 独立的 RQrun 登录、令牌缓存、验证码识别和签到流程 |

## 3. 一次活动的处理流程

1. 入口解析配置。固定方向入口确定平台组合；通用入口从 `SOURCE`、`TARGET` 选择组合。
2. 进程在 `db/activitySync.lock` 取得排他锁，避免同一工作目录中的同步任务重叠。
3. 两端客户端建立会话并获取账号身份。程序根据“来源平台与账号 + 目标平台与账号”生成状态 `scope`。
4. 定时全量/增量扫描来源活动元数据。扫描出的活动进入 `sync_transfers`；未完成队列与扫描窗口相互独立。
5. 下载来源文件，解包并验证 FIT 头、长度和 CRC。原始字节写入隔离缓存；若来源是裸 FIT，COROS 路径会生成只包装、不修改 FIT 内容的 ZIP。
6. Garmin → COROS：先向 COROS 请求临时 STS 凭证，再上传对象到凭证指定的 OSS/S3 bucket。只有对象存储确认后才提交 COROS 导入任务。
7. COROS → Garmin：读取活动文件并直接调用对应区域 Garmin 上传接口。Garmin 中国区与国际区使用各自 `garmin.cn`、`garmin.com` 客户端配置。
8. 提交前将阶段写为 `submitting`。目标响应如果直接提供可验证的目标 ID，则记为 `done`；仅表示受理时先持久化为 `accepted`，随后当次运行等待 5 秒并核对，最多 6 轮。
9. 核对优先使用目标任务 ID。没有可用任务回执时，使用活动开始时间候选范围和唯一 FIT SHA-256 一致性确认。模糊匹配不会自动标成功，也不会盲目重新 POST。
10. 运行结果汇总为完成、待核对、失败。等待或失败会返回非零退出码；完整结果通知不改变同步退出码。单活动模式不发送钉钉通知。

如果提交读超时，服务器可能已经收到活动，因此保留 `submitting` 并在当次执行中先核对。确认到目标 ID 后记为完成；若本轮查不到或遇到查询错误，记录保持待核对阶段，本轮会以失败返回，下次任务继续只读核对，绝不因“未查到”就自动重新提交。目标已明确受理但暂时没查到时，本轮结果计为待核对。

## 4. 数据文件和表设计

活动同步库为 `db/activitySync.db`；RQrun 使用独立的 `db/rq.db`。当前活动数据库中会看到旧表、三张同步表、SQLite 内部表或索引。它们不是六张同类业务表。

### `sync_transfers`：逐活动状态表

主键为 `(scope, activity_id)`。这是新版日常运行最重要的业务表。

| 字段 | SQL 类型 / 约束 | 含义 |
| --- | --- | --- |
| `scope` | `TEXT NOT NULL`，复合主键之一 | 来源平台/账号及目标平台/账号的 SHA-256 隔离键 |
| `activity_id` | `TEXT NOT NULL`，复合主键之一 | 来源端活动 ID |
| `start_ms` | `INTEGER NOT NULL` | 活动开始 Unix 毫秒；旧版记录迁入时可能为 `0` |
| `sport` | `TEXT NOT NULL DEFAULT ''` | 来源平台运动类型标识；部分客户端未提供时为空字符串 |
| `phase` | `TEXT NOT NULL DEFAULT 'pending'` | 当前同步阶段，见下方状态表 |
| `file_hash` | `TEXT NOT NULL DEFAULT ''` | 解包后的 FIT SHA-256，用于核对和保护重试 |
| `original_hash` | `TEXT NOT NULL DEFAULT ''` | 原始来源文件字节的 SHA-256 |
| `object_key` | `TEXT NOT NULL DEFAULT ''` | COROS 导入对象在 OSS/S3 上的 key |
| `object_bucket` | `TEXT NOT NULL DEFAULT ''` | 本次临时凭证返回的 bucket |
| `object_service` | `TEXT NOT NULL DEFAULT ''` | 对象存储类型，例如 `aliyun` 或 `aws` |
| `object_md5` | `TEXT NOT NULL DEFAULT ''` | COROS 导入参数所需的 ZIP MD5 |
| `object_size` | `INTEGER NOT NULL DEFAULT 0` | ZIP 文件大小（字节） |
| `task_id` | `TEXT NOT NULL DEFAULT ''` | 目标平台受理的导入任务 ID（若响应有提供） |
| `remote_id` | `TEXT NOT NULL DEFAULT ''` | 已确认的目标活动 ID |
| `last_error` | `TEXT NOT NULL DEFAULT ''` | 最近一次等待、失败或核对信息；成功时清空 |
| `updated_at` | `INTEGER NOT NULL DEFAULT unixepoch()` | 最近状态变更 Unix 秒，由 SQLite 生成 |

唯一主键为 `(scope, activity_id)`，并有 `(scope, phase, start_ms)` 查询索引 `sync_transfer_phase`。表没有 `CHECK` 限制 `phase`；有效阶段由同步引擎管理。

阶段含义：

| `phase` | 含义 | 是否会重新上传 |
| --- | --- | --- |
| `pending` | 等待下载、验证或提交 | 会按流程尝试 |
| `storage_ready` | COROS 所需的对象已上传，导入尚未可靠确认 | 重用保存的对象信息，不重新上传对象 |
| `submitting` | 已持久化提交意图；提交结果可能不确定 | 不会直接重发，先核对 |
| `accepted` | 目标表示已受理，但本地尚未确认目标活动 ID | 只核对，不重新上传 |
| `legacy_review` | 旧库有历史记录，但无法确定真实目标结果 | 只尝试核对，不自动重发 |
| `done` | 目标活动 ID 已确认 | 跳过 |

### `sync_runs`：扫描检查点

主键是 `scope`，每一账号组合和同步方向一行。此表记录“扫描到了哪里”，不记录单条活动是否成功。

| 字段 | SQL 类型 / 约束 | 含义 |
| --- | --- | --- |
| `scope` | `TEXT PRIMARY KEY` | 同步组合隔离键，与 `sync_transfers.scope` 相同 |
| `cutoff` | `INTEGER` | 配置起始时间的 Unix 毫秒；未设置时为 `0` |
| `watermark` | `INTEGER` | 已扫描到的最新来源活动开始时间，Unix 毫秒；不代表传输成功 |
| `full_scan_at` | `INTEGER` | 最近一次完整扫描完成时间，Unix 秒 |

首次运行、改变 cutoff 或距上次全量扫描 30 天会扫描完整配置范围。其他运行从 `watermark` 往前重叠 7 天，且不早于 cutoff。扫描重复页、达到页数上限或发生读取错误时不推进完成检查点。已发现的未完成记录仍会继续处理。

### `sync_legacy_binding`：旧状态迁移绑定

| 字段 | SQL 类型 / 约束 | 含义 |
| --- | --- | --- |
| `source` | `TEXT NOT NULL`，复合主键之一 | 旧记录的来源平台 |
| `target` | `TEXT NOT NULL`，复合主键之一 | 旧记录的目标平台 |
| `scope` | `TEXT NOT NULL` | 第一次迁移时绑定的账号组合 |

主键为 `(source, target)`。旧 `activity_table` 没有账号字段，因此第一次迁移某个旧方向时将它绑定到当时运行的账号组合 `scope`，后续不能随意改绑。该表用于兼容历史，不是活动运行日志。

### `activity_table`：旧版逐活动表

这是旧同步实现使用的记录表。结构为：`id INTEGER PRIMARY KEY AUTOINCREMENT`、`activity_source VARCHAR(50) NOT NULL`、`activity_target VARCHAR(50) NOT NULL`、`activity_id INTEGER NOT NULL`、`is_sync INTEGER NOT NULL DEFAULT 0`，以及 `create_time`、`update_time` 两个带本地时间默认值的时间戳字段。新引擎不在日常传输过程中更新它；新状态保存在 `sync_transfers`。初始化某方向的新版状态时，如果检测到该方向有旧记录，会将 `is_sync=1` 迁为 `done`，其他状态迁为 `legacy_review`，避免把旧版的不确定结果误当成可安全重发。升级期间保留该表，不要清空或删除。

### SQLite 内部对象

`sqlite_master`（许多数据库浏览器可能不显示或不作为普通表显示）记录 schema；`sqlite_sequence` 为旧表 `AUTOINCREMENT` 维护序号；`sync_transfer_phase` 是查询索引；`sqlite_autoindex_*` 是 SQLite 为主键建立的内部索引。这些不是应用业务状态，不要手工维护。

RQrun 数据库 `db/rq.db` 有独立的 `user_info` 表，存储经 AES 加密的邮箱、用户 ID、访问令牌及时间字段。它与运动活动状态无关。

## 5. 日常数据库查看

先确保连接的是 GearSync 实际工作目录下的 `db/activitySync.db`。以下均为只读查询，不要在数据库浏览器里误编辑数据。

### 查看活动各状态数量

```sql
SELECT scope, phase, COUNT(*) AS activities
FROM sync_transfers
GROUP BY scope, phase
ORDER BY scope, phase;
```

### 查看所有未完成活动

```sql
SELECT activity_id, phase, start_ms, task_id, remote_id, last_error,
       datetime(updated_at, 'unixepoch', 'localtime') AS updated_local
FROM sync_transfers
WHERE phase <> 'done'
ORDER BY updated_at DESC;
```

`scope` 是不可逆的账号组合哈希。新的方向未必会在 `sync_legacy_binding` 留下映射，所以只看 `scope` 不能直接推断平台/账号。可以结合固定方向任务、对应客户端账号身份、运行日志识别。不要把邮箱、密码、令牌写进数据库查询或分享的截图。

### 查某个活动及所有方向的记录

```sql
SELECT scope, activity_id, phase, start_ms, task_id, remote_id,
       last_error, datetime(updated_at, 'unixepoch', 'localtime') AS updated_local
FROM sync_transfers
WHERE activity_id = '663349283'
ORDER BY updated_at DESC;
```

若 scope 属于有旧版记录的方向，可这样看绑定：

```sql
SELECT b.source, b.target, t.activity_id, t.phase, t.remote_id, t.last_error
FROM sync_transfers AS t
LEFT JOIN sync_legacy_binding AS b ON b.scope = t.scope
WHERE t.activity_id = '663349283';
```

没有 `source`/`target` 映射不表示数据丢失，只表示该账号/方向没有旧表迁移绑定。应用通过哈希 scope 隔离状态。

### 查看运行扫描进度

```sql
SELECT scope,
       cutoff,
       CASE WHEN cutoff > 0 THEN datetime(cutoff / 1000, 'unixepoch', 'localtime') END AS cutoff_local,
       watermark,
       CASE WHEN watermark > 0 THEN datetime(watermark / 1000, 'unixepoch', 'localtime') END AS watermark_local,
       full_scan_at,
       CASE WHEN full_scan_at > 0 THEN datetime(full_scan_at, 'unixepoch', 'localtime') END AS full_scan_local
FROM sync_runs;
```

注意：`cutoff` 和 `watermark` 是毫秒，`full_scan_at` 是秒。`watermark` 仅代表来源扫描进度；要判断同步状态，查 `sync_transfers.phase`。

### 只读命令行打开

```bash
sqlite3 -readonly db/activitySync.db
```

数据库 GUI 也可以打开同一个文件；表格视图里查看，不要对 `sync_transfers` 直接编辑 phase 或 remote ID。

## 6. 故障与恢复

| 表现 | 含义与处理 |
| --- | --- |
| `done` 且有 `remote_id` | 同步已确认。正常重跑会跳过，不会再次上传。 |
| `accepted` / `submitting`，高驰/ Garmin 已可见 | 程序可能正等服务端活动列表、任务查询或文件下载结果可见。允许下次运行只读对账；不要手动改成 `done`。 |
| `accepted` / `submitting` 持续不变 | 查看 `last_error` 与同步日志。可能任务查询响应无法确认、目标 FIT 被重写、列表分页不可达或网络失败。按目标端实际活动核实后再决定后续操作，不要直接重发。 |
| `pending` | 尚未开始提交或遇到明确拒绝/可安全重试的阶段。确认日志错误已消除后，下一次任务会重试。 |
| `storage_ready` | OSS/S3 已确认对象上传；恢复时重用 key/bucket 等回执，不重复上传对象，再继续提交导入。 |
| 退出码 `1` | 至少有失败或待核对项；查看汇总和每条活动阶段。它不一定意味着目标端没有收到活动。 |
| 退出码 `2` | 方向或配置无效；检查环境变量、配置文件和固定入口方向。 |
| `Another activity sync is already running` | 同一工作目录另一进程持有锁。等它退出，不要删除锁文件试图抢跑；系统锁会随进程释放。 |

**重测限制：** `done` 状态会阻止重复传输。若确实需要重测，先核实目标端该活动已删除、暂停该方向的定时任务，并备份数据库。只针对对应 `scope + activity_id` 按维护步骤操作；不能只删除旧 `activity_table` 行，也不能删整个 `activitySync.db`。普通日常维护不需要手改数据库。

## 7. 配置与凭据

支持命令行覆盖的配置项优先级为：命令行参数 > 环境变量（包括青龙环境变量）> `scripts/config.ini` > 空值/默认值。并非每个 secret 都声明了命令行选项；生产凭据建议使用环境变量或忽略的本地配置文件。字段详表和模板见 `README.md` 与 `scripts/config.example.ini`。

| 配置组 | 主要字段 | 用途 |
| --- | --- | --- |
| 同步 | `SOURCE`、`TARGET`、`SYNC_ACTIVITY_START_TIME`、`SYNC_TIMEZONE`、`SYNC_ACTIVITY_ID` | 方向、来源活动时间范围、时区和单条模式 |
| Garmin 中国区/国际区 | 各自的 `*_SECRET` 或 `*_EMAIL` + `*_PASSWORD` | SECRET 优先；账号密码为回退登录方式 |
| COROS | `COROS_EMAIL`、`COROS_PASSWORD` | 登录高驰账号并请求区域服务和临时对象存储凭证 |
| 通知 | `DD_BOT_TOKEN`、`DD_BOT_SECRET` | 非单条运行后的钉钉结果通知 |
| RQrun | `RQ_EMAIL`、`RQ_PASSWORD`、`AESKEY` | RQrun 登录与本地令牌加密 |

不要提交 `scripts/config.ini`、令牌、密码、临时 OSS/S3 凭证、缓存 FIT 或运行数据库。Garmin 中国区和国际区必须使用对应区域凭据。COROS 登录可能使其他设备或网页会话失效，同步时避免同时在其他客户端登录。

## 8. FIT 文件和缓存

缓存路径位于 `db/activity-cache/<scope>/`，与账号组合隔离。原始文件先写临时文件、fsync 后原子改名。FIT 校验包括头部、长度和 CRC；ZIP 限制压缩展开大小、文件数、成员路径与链接类型，并要求恰好一个 FIT 文件。COROS 上传需要 ZIP 时将 FIT 放入 ZIP，不改写 FIT 数据。

缓存可能包含完整运动轨迹和个人活动信息，按敏感个人数据处理。不要公开上传缓存或日志附件。旧版 `coros-fit/`、`garmin-cn-fit/`、`garmin-global-fit/` 不会自动迁移和删除。

## 9. 运行、部署和返回码

本地通用入口：

```bash
python3 scripts/gear_sync.py
```

青龙使用六个固定方向脚本，各任务分别配置方向对应的环境变量。更新时保留 `db/activitySync.db` 和账号组合，避免新旧版本并行执行。首次迁移历史记录时，沿用原账号组合；更换账号会创建新的 scope，不会自动继承旧账号的完成状态。

| 返回码 | 含义 |
| --- | --- |
| `0` | 本轮完成且无待核对/失败，包括没有新活动 |
| `1` | 至少有失败、待核对或运行异常 |
| `2` | 配置错误或不支持的同步方向 |

## 10. RQrun 自动签到

RQrun 是与活动同步分离的脚本 `scripts/rq_sign.py`。它读取 RQ API 登录凭据并把返回的用户 ID 与访问令牌用 `AESKEY` 加密写入 `db/rq.db`。签到时优先检查缓存 token，通过网页会话和验证码接口提交签到；缓存 token 被网页拒绝时重新登录并重试。签到成功或当日已签到视为正常完成；通知失败不会覆盖已确认的签到结果。RQ 表不参与 Garmin/COROS 状态或迁移。

运行方式：

```bash
python3 scripts/rq_sign.py
```

## 11. 测试与证据边界

离线回归：

```bash
python3 tests/run_tests.py
```

测试运行器会阻止 socket 网络连接，测试使用 mock 客户端、临时 SQLite 和临时文件，不会登录真实平台或上传活动。当前同步稳定性回归包含失败传播、OSS 上传、提交不确定结果、当次等待核对、迟到活动、旧库迁移、FIT/ZIP 校验、锁和六方向入口。

真实验证记录、离线测试和 APK 静态分析是不同证据：用户已验证 Garmin 中国区 → COROS 的活动上传与新版本当次核对；任务查询响应兼容性与所有其他方向的线上行为仍需按实际日志观察。GarSync APK 逆向可以帮助理解客户端流程，但不是服务端 API 合同，也不能保证对应接口永久稳定。Garmin Personal API、颂拓接入不属于当前实现。
