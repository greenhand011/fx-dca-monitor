# fx-dca-monitor

一个面向跨境定投与换汇场景的量化监控系统。项目每天自动抓取人民币兑港币基础成本与离岸美元兑港币汇率，计算综合换汇成本，并结合历史分位策略输出日报，最终通过飞书机器人推送到群聊。

本项目的核心升级点是：

**具备高可靠性数据源容灾机制。**

即使主数据源不可用，系统也会自动降级到备用 API、历史数据，最终再退化到固定估算值，确保任务尽可能持续运行，而不是因为单一外部服务故障直接中断。

## 项目简介

`fx-dca-monitor` 适用于以下场景：

- 每日观察跨境定投前的换汇成本变化
- 辅助判断当前是否处于相对便宜或偏贵的换汇区间
- 将结果以结构化卡片形式推送到飞书，便于长期跟踪
- 借助 GitHub Actions 实现无人值守自动运行

系统的核心计算公式如下：

```text
cost = cny_hkd * usd_hkd
```

其中：

- `cny_hkd` 表示人民币换港币的基础成本
- `usd_hkd` 表示美元兑港币的离岸汇率
- `cost` 用于衡量跨境路径下的综合换汇成本

## 架构说明

系统由五个核心模块组成：

- `data_fetcher.py`：负责抓取多数据源汇率
- `calculator.py`：负责成本计算与 CSV 历史落库
- `strategy.py`：负责 90 天分位分析和联系汇率判断
- `notifier.py`：负责飞书互动卡片推送
- `main.py`：负责编排整个任务流

### 容灾架构说明

本项目的 `CNY/HKD` 数据源采用四级容灾链路：

```text
BOC（主数据源）
  ↓ 失败则切换
API（备用接口）
  ↓ 失败则切换
HISTORY（本地历史有效值）
  ↓ 再失败则切换
FALLBACK（固定估算值 0.92）
```

也可以用文字理解为：

1. 优先使用中国银行外汇牌价，准确性最高。
2. 如果中国银行页面请求失败、SSL 异常、页面结构变化，则切换到公开汇率 API。
3. 如果 API 也不可用，则回退到历史 CSV 中最后一条有效 `cny_hkd`。
4. 如果连历史数据也没有，最终使用固定估算值 `0.92`，保证程序继续运行。

这意味着：

- 外部站点故障不会立刻导致程序中断
- 飞书卡片会明确标记当前数据来源与可靠性等级
- GitHub Actions 中即使遇到偶发网络问题，也能尽量完成当天任务

此外，`USD/HKD` 也做了轻量兜底：

```text
yfinance（实时）
  ↓ 失败则切换
HISTORY（本地历史有效值）
  ↓ 再失败则切换
FALLBACK（固定估算值 7.80）
```

这样即使行情接口被限流，任务也不会因为 `USD/HKD` 获取失败而直接中断。

## 数据源说明

### 1. BOC 主数据源

来源地址：

```text
https://www.boc.cn/sourcedb/whpj/
```

处理逻辑：

- 使用 `requests + BeautifulSoup`
- 随机 User-Agent
- 解析“港币”所在行
- 提取“现汇卖出价”
- 按规则除以 `100`，得到 `cny_hkd`

这是默认首选数据源，飞书中显示为：

```text
✅ 正常（BOC）
```

### 2. API 备用数据源

来源地址：

```text
https://api.exchangerate.host/convert?from=CNY&to=HKD
```

处理逻辑：

- 请求超时设置为 `10` 秒
- 从返回 JSON 中提取 `result`
- 转换为 `float`

当 BOC 失败时，系统自动切换到该备用接口，飞书中显示为：

```text
⚠️ 备用（API）
```

### 3. HISTORY 历史兜底

来源文件：

```text
history_rates.csv
```

处理逻辑：

- 读取历史 CSV
- 选取最后一条有效的 `cny_hkd`
- 若历史数据为空或不存在，则继续降级

飞书中显示为：

```text
⚠️ 历史（HISTORY）
```

### 4. FALLBACK 固定估算值

当外部数据源和历史数据都不可用时，系统使用：

```text
0.92
```

飞书中显示为：

```text
🚨 估算（FALLBACK）
```

这不是精确行情，只是最终保底值，用来保障流程可继续执行。

## 日志与可靠性说明

所有关键容灾切换都会明确打印告警日志，例如：

```text
BOC失败，切换到API
API失败，使用历史数据
使用最终fallback估算值
```

这可以帮助你在本地或 GitHub Actions 日志中快速判断当天到底走到了哪一层兜底。

## 本地运行方法

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

Windows PowerShell：

```powershell
$env:FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/你的地址"
```

Linux / macOS：

```bash
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/你的地址"
```

### 3. 运行程序

```bash
python main.py
```

首次成功运行后，当前目录会自动生成：

```text
history_rates.csv
```

CSV 字段如下：

```text
date, cny_hkd, usd_hkd, cost
```

## 历史数据初始化

本项目支持使用真实历史汇率一次性初始化 `history_rates.csv`，从而让策略模块在第一次正式运行前就拥有足够样本，避免长期停留在冷启动状态。

### 历史数据来源

- `yfinance`：提供 `USDHKD=X` 的最近 90 天日线收盘价
- `exchangerate.host`：提供 `HKD -> CNY` 的 timeseries 历史汇率

为提高初始化成功率，脚本内部还带有公开历史镜像后备源。也就是说：

- 会优先尝试你要求的主数据源
- 若主数据源出现限流、超时、TLS 异常或接口策略变更
- 脚本会自动切换到公开历史后备源，尽量保证 `history_rates.csv` 能成功生成

### 转换逻辑

初始化时不会直接查询 `CNY -> HKD` 历史值，而是通过下式转换：

```text
CNY→HKD = 1 / (HKD→CNY)
```

然后再结合 `USD→HKD` 计算综合成本：

```text
cost = cny_hkd * usd_hkd
```

### 数据对齐规则

- 以 `USD/HKD` 的交易日为主时间轴
- 如果 `HKD/CNY` API 某天缺数据，则对齐后使用前值填充
- 最终覆盖写入 `history_rates.csv`

### 使用方法

```bash
python init_history_real.py
```

执行成功后，`history_rates.csv` 将被真实历史数据覆盖。之后再运行：

```bash
python main.py
```

策略模块通常就可以直接进入真实分位判断，而不再只是冷启动提示。

## GitHub Actions 自动运行说明

项目已内置 GitHub Actions 工作流，具备以下特性：

- 每天北京时间 `10:30` 自动运行
- 对应 UTC 时间为 `02:30`
- 支持手动触发 `workflow_dispatch`
- 自动安装依赖并执行 `python main.py`
- 从 GitHub Secrets 中读取飞书 Webhook

工作流文件位置：

```text
.github/workflows/main.yml
```

### 为什么它兼容 GitHub Actions

本项目在工程上已做以下兼容处理：

- 不依赖本地绝对路径
- 历史 CSV 使用相对项目根目录路径
- 飞书 Webhook 从环境变量读取
- 数据源失败时自动降级，减少 CI 因网络波动直接失败的概率

## 飞书机器人配置

1. 在飞书群中添加自定义机器人
2. 复制 Webhook 地址
3. 本地运行时设置环境变量 `FEISHU_WEBHOOK`
4. GitHub Actions 中将其保存为仓库密钥 `FEISHU_WEBHOOK`

GitHub 配置路径：

```text
Settings -> Secrets and variables -> Actions
```

建议密钥名：

```text
FEISHU_WEBHOOK
```

## 环境变量说明

当前项目必需/可选环境变量如下：

### FEISHU_WEBHOOK

作用：

- 指定飞书群机器人的 webhook 地址

行为：

- 已配置：程序会发送飞书互动卡片
- 未配置：程序不会报错，但会跳过飞书发送，并输出 warning 日志

## 示例输出

下面是一个“飞书截图风格”的文本示例：

```text
📊 跨境换汇日报

日期：2026-03-26
数据来源：⚠️ 备用（API）
CNY→HKD：0.923500
USD→HKD：7.812300
综合成本：7.214804

分位信息
最近90天样本 34 条，25%分位=7.180000，75%分位=7.260000，当前成本=7.214804。

策略A
🟡 中性观察：当前综合成本位于最近90天中间区间

策略B
➖ 中性：USD/HKD 位于联系汇率区间中部

策略建议
📌 建议按计划小额定投，并持续观察历史分位变化。
```

## 项目特性总结

这个系统当前具备以下工程能力：

- 自动抓取并计算跨境换汇综合成本
- 自动存储历史数据并进行分位分析
- 自动推送飞书互动卡片
- 自动运行于 GitHub Actions
- 自动切换数据源，提升稳定性
- 自动标记数据来源与可靠性等级

如果你希望继续增强，下一步很适合加入：

- `USD/HKD` 的备用数据源
- 更丰富的策略规则
- 图表化趋势展示
- 更细粒度的运行指标与告警
