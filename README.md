# APIInference

这是一个面向 `V-API` 的最小文本推理框架，先把你最需要的链路跑通：

- `jsonl` 输入
- 调用 OpenAI 兼容的文本接口
- `jsonl` 输出
- 支持并发、重试、断点续跑
- 自带一个最简单的 `test` 脚本

## 目录推荐

```text
APIInference/
├── .env.example
├── .gitignore
├── README.md
├── data/
│   ├── input/
│   │   └── smoke_test/
│   │       └── smoke_test_input.jsonl
│   └── output/
│       └── smoke_test/
│           └── smoke_test_output.jsonl
├── src/
│   └── api_inference/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── io_utils.py
│       ├── stats.py
│       └── vapi_client.py
└── test/
    └── smoke_test.py
```

我同意你的判断：主代码放在 `src/` 更好。

原因很直接：

- 业务代码和测试、数据分开，后面扩展不会乱
- 避免根目录随手堆脚本
- 后面如果加 `pyproject.toml`、打包、单测都会更顺

## 三种 env 文件的区别

### `.env`

这是你本地真正要用的配置文件，通常会放：

- `VAPI_API_KEY`
- `VAPI_BASE_URL`

这个文件里可能有真实密钥，所以必须加入 `.gitignore`。

### `.env.local`

这是一个可选的“本地覆盖文件”约定，也应该忽略。

它通常用于：

- 同一个项目里临时换一套本地配置
- 你不想改主 `.env`，只想在自己机器上覆盖一部分变量

这版程序当前主要读取你显式传入的 `--env-file`，所以你现在只用 `.env` 就够了。把 `.env.local` 也忽略掉，是为了以后扩展时不把本地私货提交上去。

### `.env.example`

这是模板文件，不放真实密钥，只放占位符，所以它应该提交到仓库里。

它的作用是：

- 告诉别人这个项目需要哪些环境变量
- 给你自己留一个安全模板

所以：

- `.env` 要忽略
- `.env.local` 要忽略
- `.env.example` 不应该忽略

## 先做什么

先复制模板：

```bash
cp .env.example .env
```

然后填上你自己的 key 和 base url。

## 最简单的可运行测试

你现在最先用这个文件：

`test/smoke_test.py`

它会做一件很简单的事：

- 从 `data/input/smoke_test/smoke_test_input.jsonl` 读取输入
- 逐条请求 V-API
- 把完整返回写到 `data/output/smoke_test/smoke_test_output.jsonl`

运行方式：

```bash
cd /home/viobert/mkx/coding/proj/APIInference
conda run -n inference python test/smoke_test.py --model 你可用的模型名
```

例如：

```bash
conda run -n inference python test/smoke_test.py --model gpt-4o-mini
```

前提是 `.env` 已经填好。

## 批量运行 CLI

主框架代码在 `src/api_inference/cli.py`。

如果你要跑批量 `jsonl`，用下面这个：

```bash
cd /home/viobert/mkx/coding/proj/APIInference
PYTHONPATH=src conda run -n inference python -m api_inference run \
  --env-file .env \
  --input data/input/smoke_test/smoke_test_input.jsonl \
  --output data/output/run_output.jsonl \
  --model 你可用的模型名 \
  --concurrency 4 \
  --temperature 0.2
```

列出你当前 key 可用模型：

```bash
cd /home/viobert/mkx/coding/proj/APIInference
PYTHONPATH=src conda run -n inference python -m api_inference models --env-file .env
```

统计输出文件：

```bash
cd /home/viobert/mkx/coding/proj/APIInference
PYTHONPATH=src conda run -n inference python -m api_inference stats --input data/output/run_output.jsonl
```

## 输入格式

每行一个 JSON 对象，支持两种写法。

### 最简单写法

```json
{"id":"demo-1","prompt":"请用一句话解释什么是梯度下降。"}
```

### 聊天写法

```json
{
  "id": "demo-2",
  "messages": [
    {"role": "system", "content": "你是一个严谨的中文助手。"},
    {"role": "user", "content": "请概括牛顿第一定律。"}
  ],
}
```

## 输出格式

成功记录会包含这些核心字段：

- `id`
- `response`

这里的 `response` 就是 API 返回的完整原始 JSON。当前这个 smoke 样例只保留 `id` 和 `response`，不再额外提取字段。

## 下一步

你先做两步：

1. 填 `.env`
2. 跑 `test/smoke_test.py`

你把实际可用模型名告诉我后，我下一轮就继续给你补：

- 更贴近你任务的数据 schema
- 批量运行的配置文件
- 更细的统计模块
