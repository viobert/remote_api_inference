# APIInference

这是一个最小可用的 OpenAI 兼容批量推理框架。现在的配置拆成两层：

- `configs/runs/*.yaml` 只描述一次运行任务
- `configs/providers/*.yaml` 负责 provider 的连接信息、环境变量和模型定价

这样日常使用只需要关心三件事：

- 选 `provider`
- 选 `model`
- 选 `input_path`

## 目录

```text
APIInference/
├── configs/
│   ├── providers/
│   │   └── vapi.yaml
│   └── runs/
│       └── default.yaml
├── env/
│   ├── examples/
│   │   └── vapi.env.example
│   └── local/
│       └── .gitkeep
├── scripts/
│   └── run_batch.sh
├── src/
│   └── inference/
└── test/
    └── smoke_test.py
```

## 配置职责

`configs/runs/default.yaml`

```yaml
provider: vapi
model: gpt-5.4-mini-low
input_path: data/input/smoke_test/smoke_test_input.jsonl
```

`configs/providers/vapi.yaml`

```yaml
name: vapi

api:
  env_files:
    - env/local/vapi.env
  api_key_env: VAPI_API_KEY
  base_url_env: VAPI_BASE_URL
  base_url: https://api.gpt.ge/v1

models:
  gpt-5.4-mini-low:
    pricing:
      input_per_1k_usd: 0.00075
      output_per_1k_usd: 0.0045
```

说明：

- provider 配置里维护连接方式和 pricing，不再放到外层 run config
- 默认优先读取 `env/local/vapi.env`

## 环境变量目录

推荐把真实密钥放在：

```bash
env/local/vapi.env
```

模板文件在：

```bash
env/examples/vapi.env.example
```

初始化：

```bash
mkdir -p env/local
cp env/examples/vapi.env.example env/local/vapi.env
```

`env/local/` 已加入 `.gitignore`，真实密钥就放这里，不再依赖根目录 `.env`。

## 运行

批量运行：

```bash
cd /home/viobert/mkx/coding/proj/APIInference
scripts/run_batch.sh
```

或者显式指定某个 run config：

```bash
cd /home/viobert/mkx/coding/proj/APIInference
scripts/run_batch.sh configs/runs/default.yaml
```

smoke test：

```bash
cd /home/viobert/mkx/coding/proj/APIInference
conda run -n inference python test/smoke_test.py \
  --provider vapi \
  --model gpt-5.4-mini-low
```

## 输出目录

输出和日志现在会按 `provider/model/run_timestamp` 分层，时间格式是 `yy-mm-dd_HHMMSS`，例如：

```text
data/output/vapi/gpt-5.4-mini-low/26-04-14_153045/
log/vapi/gpt-5.4-mini-low/26-04-14_153045/
```

这样同名模型挂在不同 provider 下时不会混在一起，同一天多次运行也不会互相覆盖。
