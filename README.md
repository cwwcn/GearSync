# GearSync：Garmin 与 COROS 运动数据同步工具

GearSync 用于在 Garmin 中国区、Garmin 国际区和 COROS（高驰）之间同步或迁移运动数据，并提供同步结果通知和 RQrun 自动签到功能。

## 功能

- 支持 Garmin 中国区、Garmin 国际区、COROS 任意两个平台之间的双向同步，共 6 种方向。
- 支持指定同步起始日期或时间；不指定时同步全部历史数据。
- Garmin 支持令牌和账号密码两种登录方式，配置令牌时优先使用令牌。
- 使用本地 SQLite 记录各同步方向的处理状态，避免重复处理已成功同步的活动。
- 支持通过钉钉机器人发送同步结果。
- 提供独立的 RQrun 自动签到脚本。

## 使用前注意

1. 同步涉及 Garmin 国际区时，运行环境必须能够正常访问 Garmin 国际区服务。
2. COROS 仅允许单设备登录。同步期间不要同时登录或打开 COROS 网页端，否则可能导致登录状态失效或同步失败。
3. `SYNC_ACTIVITY_START_TIME` 留空会读取全部历史活动。首次运行前请确认同步方向和时间范围。

## 快速开始

### 1. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

### 2. 创建本地配置

```bash
cp scripts/config.example.ini scripts/config.ini
```

`scripts/config.ini` 只用于本地运行和 IDE 调试，已被 Git 忽略。请勿将账号、密码或令牌写入 `config.example.ini`。

### 3. 配置同步方向和账号

例如，从 Garmin 中国区同步 2025 年 7 月 1 日之后的活动到 Garmin 国际区：

```ini
[SYNC_SETTINGS]
SOURCE = GARMIN_CN
TARGET = GARMIN_GLOBAL
SYNC_ACTIVITY_START_TIME = 20250701
```

同时在 `[GARMIN_CN]` 和 `[GARMIN_GLOBAL]` 中配置对应的令牌，或配置账号和密码。

### 4. 启动同步

```bash
python3 scripts/gear_sync.py
```

## 配置说明

配置读取优先级为：

```text
命令行参数 > 系统或青龙环境变量 > scripts/config.ini > 默认空值
```

### 同步配置

| 参数 | 说明 | 示例 |
| --- | --- | --- |
| `SOURCE` | 数据来源平台 | `GARMIN_CN`、`GARMIN_GLOBAL`、`COROS` |
| `TARGET` | 数据目标平台，不能与来源相同 | `GARMIN_CN`、`GARMIN_GLOBAL`、`COROS` |
| `SYNC_ACTIVITY_START_TIME` | 同步起始时间；留空表示全部历史数据 | `20250701` 或 `20250701083001` |
| `DOMAIN` | 获取 Garmin 令牌时选择区域 | 中国区使用 `CN`，国际区使用 `COM` |

只填写日期时，程序按当天 `00:00:01` 作为起始时间；完整格式为 `YYYYMMDDHHMMSS`。

### 平台登录配置

| 参数 | 说明 |
| --- | --- |
| `GARMIN_CN_SECRET` | Garmin 中国区登录令牌；配置后优先使用 |
| `GARMIN_CN_EMAIL` | Garmin 中国区账号；未配置令牌时必填 |
| `GARMIN_CN_PASSWORD` | Garmin 中国区密码；未配置令牌时必填 |
| `GARMIN_GLOBAL_SECRET` | Garmin 国际区登录令牌；配置后优先使用 |
| `GARMIN_GLOBAL_EMAIL` | Garmin 国际区账号；未配置令牌时必填 |
| `GARMIN_GLOBAL_PASSWORD` | Garmin 国际区密码；未配置令牌时必填 |
| `COROS_EMAIL` | COROS 登录账号 |
| `COROS_PASSWORD` | COROS 登录密码 |

Garmin 登录顺序：

1. 配置了对应区域的 `GARMIN_*_SECRET` 时，使用令牌登录。
2. 未配置令牌时，使用对应区域的邮箱和密码登录。

![Garmin MFA 登录](doc/MFA%E7%99%BB%E5%BD%95.png)

### 通知与 RQrun 配置

| 参数 | 说明 |
| --- | --- |
| `DD_BOT_TOKEN` | 钉钉机器人 Webhook Token；不使用通知时留空 |
| `DD_BOT_SECRET` | 钉钉机器人签名密钥；不使用通知时留空 |
| `AESKEY` | RQrun 本地数据加密密钥，最长 32 字符，建议使用 16、24 或 32 字符 |
| `RQ_EMAIL` | RQrun 登录账号 |
| `RQ_PASSWORD` | RQrun 登录密码 |

### 命令行示例

通用入口支持通过命令行覆盖常用配置：

```bash
python3 scripts/gear_sync.py \
  --SOURCE GARMIN_CN \
  --TARGET GARMIN_GLOBAL \
  --SYNC_ACTIVITY_START_TIME 20250701 \
  --GARMIN_CN_EMAIL user@example.com \
  --GARMIN_CN_PASSWORD '******' \
  --GARMIN_GLOBAL_EMAIL user@example.com \
  --GARMIN_GLOBAL_PASSWORD '******'
```

生产环境建议使用环境变量传递敏感配置，避免密码出现在命令历史或任务日志中。

## 程序入口

### 通用同步入口

[gear_sync.py](scripts/gear_sync.py) 根据 `SOURCE` 和 `TARGET` 自动选择同步方向，适合大多数使用场景。

### 固定方向入口

固定方向脚本不读取 `SOURCE` 和 `TARGET`，适合在青龙中为不同同步方向分别创建任务。

| 同步方向 | 入口 |
| --- | --- |
| COROS → Garmin 中国区 | [coros_to_garmin_cn.py](scripts/coros_to_garmin_cn.py) |
| COROS → Garmin 国际区 | [coros_to_garmin_global.py](scripts/coros_to_garmin_global.py) |
| Garmin 中国区 → COROS | [garmin_cn_to_coros.py](scripts/garmin_cn_to_coros.py) |
| Garmin 国际区 → COROS | [garmin_global_to_coros.py](scripts/garmin_global_to_coros.py) |
| Garmin 中国区 → Garmin 国际区 | [garmin_cn_to_garmin_global.py](scripts/garmin_cn_to_garmin_global.py) |
| Garmin 国际区 → Garmin 中国区 | [garmin_global_to_garmin_cn.py](scripts/garmin_global_to_garmin_cn.py) |

### 获取 Garmin 登录令牌

在 `scripts/config.ini` 中配置 `DOMAIN` 和对应区域的 Garmin 邮箱、密码，然后运行：

```bash
PYTHONPATH=scripts python3 scripts/utils/get_garmin_secret.py
```

脚本输出的长字符串即为登录令牌。请将其保存到对应的 `GARMIN_CN_SECRET` 或 `GARMIN_GLOBAL_SECRET`，并妥善保管。

### RQrun 自动签到

配置 `AESKEY`、`RQ_EMAIL` 和 `RQ_PASSWORD` 后运行：

```bash
python3 scripts/rq_sign.py
```

如果修改 RQrun 密码后本地令牌状态异常，请先备份或重命名 `db/rq.db`，再让程序重新创建数据库。

## 青龙面板部署

建议使用 Debian 版本镜像 `whyour/qinglong:debian`。普通镜像可能无法正确安装部分二进制依赖，RQrun 验证码识别相关依赖尤其容易受影响。

1. 在青龙中安装 [requirements.txt](requirements.txt) 中的 Python 依赖。

   ![安装依赖](doc/%E9%9D%92%E9%BE%99%E5%AE%89%E8%A3%85%E4%BE%9D%E8%B5%96.png)

2. 确认依赖均已成功安装。

   ![依赖状态](doc/%E9%9D%92%E9%BE%99%E4%BE%9D%E8%B5%96.png)

3. 使用青龙环境变量配置同步参数和登录信息。

   ![配置环境变量](doc/%E9%9D%92%E9%BE%99%E9%85%8D%E7%BD%AE%E7%8E%AF%E5%A2%83%E5%8F%98%E9%87%8F.png)

4. 在订阅管理中拉取仓库并创建定时任务。首次拉取可临时打开“自动添加任务”和“自动删除任务”，完成后关闭，避免后续更新重新添加已经移除的任务。

   ![订阅管理](doc/%E8%AE%A2%E9%98%85%E7%AE%A1%E7%90%86.png)

   ![定时任务](doc/%E5%AE%9A%E6%97%B6%E4%BB%BB%E5%8A%A1.png)

   ![关闭自动添加和删除](doc/%E5%85%B3%E6%8E%89%E8%87%AA%E5%8A%A8%E6%B7%BB%E5%8A%A0%E5%92%8C%E5%88%A0%E9%99%A4.png)

5. 运行任务并检查日志和通知结果。

   ![运行效果](doc/%E8%BF%90%E8%A1%8C%E6%95%88%E6%9E%9C%E5%9B%BE.png)

## 本地数据

运行过程中会在以下目录保存数据：

- `db/`：活动同步状态和 RQrun 登录状态。
- `coros-fit/`：从 COROS 下载的活动文件。
- `garmin-cn-fit/`：从 Garmin 中国区下载或解压的活动文件。
- `garmin-global-fit/`：从 Garmin 国际区下载或解压的活动文件。

这些目录均为本地运行数据，不应提交到 Git。升级、清理或迁移前建议先备份。

## 离线回归测试

项目使用 Python 标准库 `unittest`，不需要额外安装测试框架：

```bash
python3 tests/run_tests.py
```

测试使用临时数据库、临时 FIT 目录和假客户端，并在测试运行器中禁止网络连接，因此不会登录真实账号、请求第三方接口或上传运动数据。

## 后续计划

- 按运动类型筛选同步数据，例如只同步跑步或骑行活动。
- 增加 GitHub Actions 运行方式。
- 持续补充回归测试并完善异常诊断。

## 致谢

本项目参考并重写自 XiaoSiHwang/garmin-sync-coros，感谢原作者的开源贡献。

## 免责声明

本工具仅限个人学习和研究使用，不得用于商业或非法用途。使用者应自行承担第三方平台账号和数据操作风险。

如有问题，可联系：cwwcnpds@gmail.com
