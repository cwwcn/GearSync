# 佳明国际区、佳明中国区、高驰三个平台运动数据任意方向同步与迁移工具。

## 致谢

- 该脚本是根据XiaoSiHwang/garmin-sync-coros项目为重要参考的重写与新增升级，非常感谢大佬的无私奉献！！！！！！

## 新增与修改

- 增加了佳明国际区和佳明中国区之间任意方向的数据同步。
- 增加了同步数据时间节点的可选择。
- 修复了高驰往佳明同步失败的问题。
- 增加了钉钉机器人推送结果功能。
- 整合了RQrun自动签到。
- 重构了些方法，修改了些逻辑，完善了些细节...
- 等等...

## 注意，特别是第1条！

**1：如果你的数据同步任务涉及到佳明国际区，请一定要确保运行脚本的网络环境是能够顺利访问国外网站的（原因你懂），否则会导致数据同步失败！！！！！！！**

2：由于高驰平台只允许单设备登录，同步期间如果打开高驰网页可能会影响到数据同步导致同步失败，同步期间不要打开网页。

## 参数配置说明

|           参数名            |                      备注                      |                                      案例                                       |
|:------------------------:|:--------------------------------------------:|:-----------------------------------------------------------------------------:|
|          SOURCE          |                 数据源(数据从哪里来)                  |                       分为：GARMIN_CN、GARMIN_GLOBAL、COROS                        |
|          TARGET          |                 数据目标（数据到哪里去）                 |                       分为：GARMIN_CN、GARMIN_GLOBAL、COROS                        |
| SYNC_ACTIVITY_START_TIME |                  同步的数据时间节点                   | 格式：%Y%m%d%H%M%S <br/>例如：20250701083001或20250701<br/>（可指定日期与时间或只写日期，默认0点0分1秒 ） |
|     GARMIN_CN_EMAIL      |                 佳明中国区登录帐号邮箱                  |                                                                               |
|    GARMIN_CN_PASSWORD    |                  佳明中国区登录密码                   |                                                                               |
|   GARMIN_GLOBAL_EMAIL    |                 佳明国际区登录帐号邮箱                  |                                                                               |
|  GARMIN_GLOBAL_PASSWORD  |                  佳明国际区登录密码                   |                                                                               |
|       COROS_EMAIL        |                   高驰 登录邮箱                    |                                                                               |
|      COROS_PASSWORD      |                   高驰 登录密码                    |                                                                               |
|      DD_BOT_TOKEN      |              钉钉机器人webhook token              |                                                                               |
|      DD_BOT_SECRET      |                 钉钉机器人secret                  |                                                                               |
|      AESKEY      | 如果QRrun签到，这个是必填项，自定义，长度不超过32字符，最好是16、24、32字符 |                        例如随便写个aeskey：suibianxiegeaeskey                        |
|      RQ_EMAIL      |          如果QRrun签到，这个是必填项，你RQ的登录账号           |                                                                               |
|      RQ_PASSWORD      |          如果QRrun签到，这个是必填项，你RQ的登录密码           |                                                                               |

例如你打算 ：从 佳明中国区 2025年7月1日以后的数据开始 同步到到佳明国际区，然后将执行结果推送到自己的钉钉机器人。那么参数配置情况如下：

- SOURCE = GARMIN_CN
- TARGET = GARMIN_GLOBAL
- SYNC_ACTIVITY_START_TIME = 20250701
- GARMIN_CN_EMAIL = XXXX@XXXX.com（你自己的佳明中国区登录邮箱号）
- GARMIN_CN_PASSWORD = **********（你自己的佳明中国区登录密码）
- GARMIN_GLOBAL_EMAIL = XXXX@XXXX.com（你自己的佳明国际区登录邮箱号）
- GARMIN_GLOBAL_PASSWORD = **********（你自己的佳明国际区登录密码）
- DD_BOT_TOKEN = *********（你钉钉机器人的token）
- DD_BOT_SECRET = SEC*****（你钉钉机器人的secret）

## 运行启动说明

### 脚本支持 佳明中国区、佳明国际区和高驰 三个平台相互之间总共6种同步方式以及RQrun签到。

**同步数据每种方式如不指定时间节点即为全部数据迁移！！**

一、你可以从以下程序入口启动，该种启动方式因明确了数据同步方向，故无需配置SOURCE和TARGET参数（就算你配了也没用），只需要配两方账号密码以及时间节点即可：

- 从高驰同步数据到佳明中国区：coros_to_garmin_cn.py
- 从高驰同步数据到佳明国际区：coros_to_garmin_global.py
- 从佳明中国区同步数据到高驰：garmin_cn_to_coros.py
- 从佳明国际区同步数据到高驰：garmin_global_to_coros.py
- 从佳明国际区同步数据到佳明中国区：garmin_global_to_garmin_cn.py
- 从佳明中国区同步数据到佳明国际区：garmin_cn_to_garmin_global.py

二、同时你也可以直接在以下入口使用通用方式启动程序，该方式则必须指定配置SOURCE和TARGET，两方账号账号密码以及时间节点，程序会根据SOURCE和TARGET配置情况自动选择执行哪种同步方式：

- gear_sync.py

三、RQrun签到从这启动：
- rq_sign.py（如果后期改RQ密码后，执行签到报错了，就把rq.db删了重新运行！）

**数据同步启动方式选择建议：如果你的需求只涉及一个方向的同步，直接使用方式二的gear_sync.py启动；如果你既要又要，那就按需选方式一里边的启动方式，这时就不要再用方式二了。**

## 项目运行方案

### 参数配置优先级为：命令行参数 > 青龙环境变量 > 配置文件

### 一、你可以在本地python3环境下运行，运行前请确保python3环境已安装相关依赖包（[requirements.txt](requirements.txt)），命令行启动程序时指定参数名和参数值。
- 如：python3 gear_sync.py --SOURCE GARMIN_CN --TARGET GARMIN_GLOBAL --SYNC_ACTIVITY_START_TIME 20250701
  --GARMIN_CN_EMAIL XXXX@XXXX.com --GARMIN_CN_PASSWORD *** --GARMIN_GLOBAL_EMAIL XXXX@XXXX.com
  --GARMIN_GLOBAL_PASSWORD ****

### 二、如果你懂一点代码也可以通过修改配置文件[config.ini](scripts/config.ini)<span style="color:#E4393C;font-weight:bold;">(看好是ini文件，别改错了)</span>来配置参数后，将程序打包成Docker镜像，搭配系统定时任务使用Docker方式去运行。
- 参数配置示例：![参数配置文件.png](doc/%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E6%96%87%E4%BB%B6.png)

### 三、当然你既然都能docker方式运行了，那肯定也不差部署个青龙面板了，对吧！如果有条件的话，我最最推荐的还是使用青龙面板来运行，直观、方便、易管理、易操作。（如果你需要RQ签到的话，记得拉debian版本的青龙 image: whyour/qinglong:debian，普通版本有些依赖包安装不上）

- 1.使用青龙跑定时任务之前，须装依赖包（[requirements.txt](requirements.txt)）！！
![青龙安装依赖.png](doc/%E9%9D%92%E9%BE%99%E5%AE%89%E8%A3%85%E4%BE%9D%E8%B5%96.png)
---
- 2.请确保每一个依赖的安装状态都是已安装状态。
![青龙依赖.png](doc/%E9%9D%92%E9%BE%99%E4%BE%9D%E8%B5%96.png)
---
- 3.根据自己的需求，在青龙中配置环境变量。
![青龙配置环境变量.png](doc/%E9%9D%92%E9%BE%99%E9%85%8D%E7%BD%AE%E7%8E%AF%E5%A2%83%E5%8F%98%E9%87%8F.png)
---
- 4.订阅管理里拉代码，设置定时任务。\
这里的链接不一定是我的仓库链接，如果你fork到了自己的仓库下，请将链接替换成自己的仓库链接。\
编辑订阅页面最下边还有 “自动添加任务”，“自动删除任务”，这俩开关首次拉代码建议打开。开启后它会把项目里所有的py文件都自动帮你添加任务到定时服务里，首次拉完代码后就关掉。
![订阅管理.png](doc/%E8%AE%A2%E9%98%85%E7%AE%A1%E7%90%86.png)
到定时任务里根据需求删除掉用不上的定时任务。
![定时任务.png](doc/%E5%AE%9A%E6%97%B6%E4%BB%BB%E5%8A%A1.png)
回到订阅管理再把这两个按钮关掉保存，以防下次同步代码后被删除的定时任务再次被添加。
![关掉自动添加和删除.png](doc/%E5%85%B3%E6%8E%89%E8%87%AA%E5%8A%A8%E6%B7%BB%E5%8A%A0%E5%92%8C%E5%88%A0%E9%99%A4.png)
（至此全部配置就完成了）
---
- 5.运行程序效果：
![运行效果图.png](doc/%E8%BF%90%E8%A1%8C%E6%95%88%E6%9E%9C%E5%9B%BE.png)

## 将来可能会做的
- [x] 增加钉钉消息提醒。
- [x] 增加RQrun自动签到。
- [ ] 持续完善细节，尽量做到不出bug。
- [ ] 根据运动类型筛选同步数据，例如只同步跑步数据、只同步骑行数据等。
- [ ] GitHub Actions 运行方式。

## 免责声明
- 该工具仅限用于个人学习和研究使用，不得用于任何商业或者非法用途。如有任何问题可Email：cwwcnpds@gmail.com 与我联系！

## 最后真的再次感谢XiaoSiHwang大佬的开源项目，没有他就没有这个项目！！！！

