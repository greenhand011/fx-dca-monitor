# fx-dca-monitor

跨境定投换汇量化监控助手。项目会自动抓取中国银行港币外汇牌价与离岸 USD/HKD 汇率，计算综合换汇成本，并基于历史数据给出简单量化策略判断，最后通过飞书机器人推送日报。

## 项目功能

1. 获取中国银行“港币”现汇卖出价，并换算为 `CNY→HKD` 成本。
2. 获取离岸市场 `USDHKD=X` 汇率。
3. 计算综合成本：`cost = cny_hkd * usd_hkd`。
4. 将历史结果写入 `history_rates.csv`。
5. 使用最近 90 天历史成本进行分位分析，并结合港币联系汇率区间给出建议。
6. 通过飞书 Webhook 发送互动卡片日报。

## 项目结构

```text
fx-dca-monitor/
├── main.py
├── data_fetcher.py
├── calculator.py
├── strategy.py
├── notifier.py
├── utils.py
├── requirements.txt
├── README.md
└── .github/workflows/main.yml
```

## 本地运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置飞书 Webhook

Windows PowerShell：

```powershell
$env:FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/你的地址"
```

Linux / macOS：

```bash
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/你的地址"
```

如果未配置 `FEISHU_WEBHOOK`，程序仍然可以运行，但会跳过飞书推送，并在日志中给出提示。

### 3. 运行主程序

```bash
python main.py
```

运行成功后会在当前目录生成或更新：

```text
history_rates.csv
```

CSV 字段如下：

```text
date, cny_hkd, usd_hkd, cost
```

## 策略说明

### 策略 A：成本分位判断

1. 读取最近 90 天历史数据；
2. 计算 `cost` 的 25% 与 75% 分位；
3. 若当前成本低于 25% 分位，提示 `🟢 强烈建议`；
4. 若当前成本高于 75% 分位，提示 `🔴 暂缓操作`；
5. 若有效样本少于 10 条，则视为冷启动，仅提示继续积累数据。

### 策略 B：港币联系汇率强弱判断

1. `usd_hkd <= 7.78`：提示 `⭐️ 强`；
2. `usd_hkd >= 7.83`：提示 `⚠️ 弱`；
3. 其他区间提示中性观察。

## GitHub Actions 说明

项目已内置 GitHub Actions 工作流：

1. 每天北京时间 `10:30` 自动运行；
2. 对应 UTC 时间为 `02:30`；
3. 也支持手动触发 `workflow_dispatch`；
4. 工作流会自动安装依赖并执行 `python main.py`。

工作流文件位置：

```text
.github/workflows/main.yml
```

## 飞书 Webhook 配置说明

1. 在飞书群中添加自定义机器人；
2. 复制机器人的 Webhook 地址；
3. 本地运行时设置环境变量 `FEISHU_WEBHOOK`；
4. GitHub 上运行时，将同名密钥保存到仓库 `Settings -> Secrets and variables -> Actions` 中。

建议将 GitHub Secrets 的名字设置为：

```text
FEISHU_WEBHOOK
```

## 注意事项

1. 中国银行网页结构若发生变化，可能需要调整解析逻辑；
2. yfinance 受网络环境和上游数据接口影响，偶发失败时会自动重试；
3. 本项目定位为辅助监控工具，不构成任何投资建议。
