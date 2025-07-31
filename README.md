# 佳明国际区、佳明中国区、高驰三个平台运动数据任意方向同步与迁移工具。

## 致谢

- 该脚本是根据XiaoSiHwang的garmin-sync-coros项目为参考的改写与新增升级，非常感谢大佬的无私奉献！！！！！！

## 新增与修改

- 增加了佳明国际区和佳明中国区之间任意方向的数据同步。
- 增加了同步数据时间节点的可选择。
- 修复了高驰往佳明同步失败的问题。
- 重构了些方法，修改了些逻辑，完善了些细节...
- 等等...

## 注意，特别是第1条！

<span style="color:#E4393C;font-weight:bold;">
1：如果你的数据同步任务涉及到佳明国际区，请一定要确保运行脚本的网络环境是能够顺利访问国外网站的（原因你懂），否则是会导致数据同步失败！！！！！！！</span>

2：由于高驰平台只允许单设备登录，同步期间如果打开高驰网页可能会影响到数据同步导致同步失败，同步期间不要打开网页。

## 参数配置说明

|           参数名            |     备注      |                                       案例                                        |
|:------------------------:|:-----------:|:-------------------------------------------------------------------------------:|
|          SOURCE          |   数据源(从哪)   |                        分为：GARMIN_CN、GARMIN_GLOBAL、COROS                         |
|          TARGET          |  数据目标（到哪）   |                        分为：GARMIN_CN、GARMIN_GLOBAL、COROS                         |
| SYNC_ACTIVITY_START_TIME |  同步的数据时间节点  | 格式：%Y%m%d%H%M%S <br/>例如：20250701083001或20250701<br/>（可以指定日期与时间点或只写日期，默认0点0份1秒 ） |
|     GARMIN_CN_EMAIL      | 佳明中国区登录帐号邮箱 |                                                                                 |
|    GARMIN_CN_PASSWORD    |  佳明中国区登录密码  |                                                                                 |
|   GARMIN_GLOBAL_EMAIL    | 佳明国际区登录帐号邮箱 |                                                                                 |
|  GARMIN_GLOBAL_PASSWORD  |  佳明国际区登录密码  |                                                                                 |
|       COROS_EMAIL        |   高驰 登录邮箱   |                                                                                 |
|      COROS_PASSWORD      |   高驰 登录密码   |                                                                                 |

例如你打算 ：从 佳明中国区 2025年7月1日以后的数据开始 同步到到佳明国际区，那么参数配置情况如下：

- SOURCE ： GARMIN_CN
- TARGET ： GARMIN_GLOBAL
- SYNC_ACTIVITY_START_TIME ： 20250701
- GARMIN_CN_EMAIL ： XXXX@XXXX.com（你自己的佳明中国区登录邮箱号）
- GARMIN_CN_PASSWORD ： **********（你自己的佳明中国区登录密码）
- GARMIN_GLOBAL_EMAIL ： XXXX@XXXX.com（你自己的佳明国际区登录邮箱号）
- GARMIN_GLOBAL_PASSWORD ： **********（你自己的佳明国际区登录密码）

## 运行说明

脚本支持 佳明中国区、佳明国际区和高驰 三个平台相互之间总共6种同步方式。

<span style="color:#E4393C;font-weight:bold;">每种方式如不指定时间节点即为全部数据迁移。</span>

你可以从以下程序入口启动，该种启动方式因明确了数据同步方向，故无需配置SOURCE和TARGET参数（就算你配了也没用），只需要配两方账号密码以及时间节点即可：

- 从高驰同步数据到佳明中国区：coros_to_garmin_cn.py
- 从高驰同步数据到佳明国际区：coros_to_garmin_global.py
- 从佳明中国区同步数据到高驰：garmin_cn_to_coros.py
- 从佳明国际区同步数据到高驰：garmin_global_to_coros.py
- 从佳明国际区同步数据到佳明中国区：garmin_global_to_garmin_cn.py
- 从佳明中国区同步数据到佳明国际区：garmin_cn_to_garmin_global.py

同时你也可以直接在以下入口启动程序，该方式则必须指定配置SOURCE和TARGET，两方账号账号密码以及时间节点，程序会根据SOURCE和TARGET配置情况自动选择执行哪种同步方式：

- gear_sync.py

## 运行方式

参数配置优先级为：命令行参数 > 青龙环境变量 > 配置文件

一、你可以在本地python3环境下运行，运行前请确保python3环境已安装相关依赖包（[requirements.txt](requirements.txt)
  ），命令行启动程序时指定参数名和参数值。
- 如：python3 gear_sync.py --SOURCE GARMIN_CN --TARGET GARMIN_GLOBAL --SYNC_ACTIVITY_START_TIME 20250701
  --GARMIN_CN_EMAIL XXXX@XXXX.com --GARMIN_CN_PASSWORD *** --GARMIN_GLOBAL_EMAIL XXXX@XXXX.com
  --GARMIN_GLOBAL_PASSWORD ****

二、如果你懂一点代码也可以通过修改配置文件[config.ini](scripts/config.ini)<span style="color:#E4393C;font-weight:bold;">(
看好是ini文件，别改错了)</span>来配置参数后，将程序打包成Docker镜像，搭配系统定时任务使用Docker方式去运行。
- 参数配置示例：![参数配置文件.png](doc/%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E6%96%87%E4%BB%B6.png)

三、如果有条件的话，我最最推荐的还是使用青龙面板来运行，方便易操作。（当然你既然都能docker方式运行了，那肯定也不差部署个青龙面板了，对吧！）

- 使用青龙跑定时任务之前，须装依赖包（[requirements.txt](requirements.txt)）！！
![青龙安装依赖.png](doc/%E9%9D%92%E9%BE%99%E5%AE%89%E8%A3%85%E4%BE%9D%E8%B5%96.png)
- 请确保每一个依赖的安装状态都是已安装状态。
![青龙依赖.png](doc/%E9%9D%92%E9%BE%99%E4%BE%9D%E8%B5%96.png)
- 根据自己的需求，在青龙中配置环境变量。
![青龙配置环境变量.png](doc/%E9%9D%92%E9%BE%99%E9%85%8D%E7%BD%AE%E7%8E%AF%E5%A2%83%E5%8F%98%E9%87%8F.png)

- todo 配置定时任务

## 将来可能会做的
- [ ] 持续完善细节，尽量做到不出bug。
- [ ] 根据运动类型筛选同步数据，例如只同步跑步数据、只同步骑行数据等。
- [ ] GitHub Actions 运行方式。

## 最后真的再次感谢XiaoSiHwang大佬的开源项目，让我在该脚本开发过程中参考了很多代码！！！

