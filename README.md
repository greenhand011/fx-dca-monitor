# fx-dca-monitor

`fx-dca-monitor` 是一个面向跨境定投场景的资金调度引擎。它不是单纯告诉你“汇率是多少”，而是帮助你判断今天该换多少、要不要提前换、要不要把部分资金换回人民币。

## 项目简介

这个系统每天会读取历史汇率数据，结合当前行情，给出更人话的资金调度建议：

- 什么时候适合加大人民币换港币
- 什么时候适合降低换汇力度
- 什么时候可以提前囤一点港币
- 什么时候可以考虑把部分资金换回人民币

核心目标不是预测价格，而是把资金分配得更顺手、更稳定。

## 代码结构

```text
fx-dca-monitor/
├── main.py
├── data_fetcher.py
├── calculator.py
├── strategy.py
├── notifier.py
├── portfolio.py
├── utils.py
├── init_history_real.py
├── requirements.txt
├── README.md
└── .github/workflows/main.yml
```

## 编码说明

项目已统一为 UTF-8 编码，所有 Python 文件头部都包含：

```python
# -*- coding: utf-8 -*-
```

这样可以避免 GitHub Actions 在 UTF-8 环境里因为 GBK / ANSI 文件而报错。

## 本地运行

### 安装依赖

```bash
pip install -r requirements.txt
```

### 初始化真实历史数据

先生成最近 90 天的真实历史汇率，确保策略不是冷启动：

```bash
python init_history_real.py
```

### 运行主程序

```bash
python main.py
```

运行后会更新 `history_rates.csv`，并发送飞书日报。

## 历史数据初始化

本项目支持真实历史汇率初始化，首次运行时建议先执行：

```bash
python init_history_real.py
```

### 数据来源

- `yfinance`：获取 `USDHKD=X` 的近 90 天日线收盘价
- `exchangerate.host`：获取 `HKD -> CNY` 的 timeseries 历史数据
- 公开历史后备源：当上游接口异常时，脚本会自动切换到公开历史数据源继续初始化

### 转换逻辑

```text
CNY → HKD = 1 / (HKD → CNY)
cost = cny_hkd * usd_hkd
```

### 对齐规则

- 以 `USD/HKD` 日期为主
- `HKD/CNY` 缺失时使用前值填充
- 最终覆盖写入 `history_rates.csv`
- 生成结果通常不少于 60 条记录

## 资金调度逻辑

这个项目只重点择时 `RMB → HKD`，不把“每一次港币换美元”当成主要择时对象，原因很简单：

1. 真正影响定投节奏的，是你什么时候把人民币换成港币去执行计划。
2. 港币联系汇率机制本身比较稳定，`HKD → USD` 更多时候只是短线资金摆放，不是主要收益来源。
3. 分位数能帮助我们识别“当前换汇成本是在偏便宜、正常，还是偏贵的位置”，这样资金调度会更有纪律。

人话版理解就是：

- 低位时，多换一点，提前把子弹准备好
- 中位时，按计划来
- 高位时，少换一点，甚至等一等

### 三层策略

#### 策略 1：人民币 → 港币

- 低于 25% 分位：强力加仓，建议 `+50% ~ +100%`
- 高于 75% 分位：明显减仓，建议 `-50% ~ -100%`
- 中间区间：正常定投，保持节奏

#### 策略 2：是否提前囤港币

- 当前处于低位，且港币余额不够 3 个月预算时
- 建议提前储备 3-6 个月港币

#### 策略 3：是否换回人民币

- 高位时，可以考虑部分换回人民币
- 低位时，不建议换回人民币

## 飞书输出

飞书日报会展示这些内容：

1. 汇率数据
2. 当前市场位置：低位 / 中位 / 高位
3. 换汇建议：百分比 + 示例金额
4. 是否囤港币
5. 是否换回人民币
6. 港币 → 美元建议

卡片会尽量使用自然语言，不直接暴露 q25 / q75 数字。

## GitHub Actions

工作流默认每天北京时间 10:30 自动执行，对应 UTC 02:30。

CI 里会先执行：

```bash
python init_history_real.py
```

然后再执行：

```bash
python main.py
```

这样可以保证历史样本先初始化，再运行策略分析。

## 飞书机器人配置

1. 在飞书群里添加自定义机器人
2. 复制机器人 Webhook
3. 本地运行时设置环境变量 `FEISHU_WEBHOOK`
4. GitHub Actions 中把同名变量放到 `Secrets`

示例：

```powershell
$env:FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
```

## 示例输出

```text
📊 当前汇率位置：低位（人民币强）

建议：+50% ~ +100%
示例金额：2000 → 3000 ~ 4000 RMB

是否囤港币：建议提前储备 3-6 个月港币
是否换回人民币：🚫 不建议换回人民币
港币 → 美元建议：USD/HKD 偏强，若有美元需求可分批换入。
```

## 常见文件

- `history_rates.csv`：历史汇率数据
- `init_history_real.py`：真实历史初始化脚本
- `.github/workflows/main.yml`：GitHub Actions 工作流

