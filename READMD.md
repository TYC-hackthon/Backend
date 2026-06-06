# Git-like AI Chat 後端

這是專案的 Flask 後端，目前提供簡易 LLM 對話 API，供前端選擇模型並送出聊天內容。後端目前支援 Ollama 與 Gemini 兩種 Provider。

## 主要架構

- `main.py`：Flask app 入口，包含 API route、模型清單、Provider 呼叫邏輯。
- `core/web.py`：既有回應格式工具。
- `core/general.py`、`core/log.py`：既有通用工具與紀錄工具。
- `pyproject.toml`：Python 專案與相依套件設定。

## API

- `GET /api/health`：檢查後端狀態。
- `GET /api/models`：回傳前端模型選單所需的 Provider 與 Model 清單。
- `POST /api/chat`：接收 `provider`、`model`、`messages`，呼叫指定模型並回傳 assistant 訊息。

`POST /api/chat` payload 範例：

```json
{
  "provider": "ollama",
  "model": "llama3.1",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." }
  ]
}
```

## Provider 設定

- Ollama：預設使用 `http://localhost:11434`，可用 `OLLAMA_BASE_URL` 覆蓋。
- Gemini：需設定 `GEMINI_API_KEY` 後再啟動後端。

## 開發指令

```bash
uv sync
uv run python main.py
```

開發伺服器預設為 `http://127.0.0.1:5000/`。
