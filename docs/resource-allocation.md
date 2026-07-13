# Resource Allocation

Last successful inventory: 2026-06-30. Nvidia-1 was unavailable at the final
13 July office-network check, so the split below is historical until re-attested.

## Last-observed intended split

- Nvidia-1 (`<NVIDIA1_HOST>`) is the intended control plane.
  - Runs the marketing agent, n8n, Postiz, Mautic, Twenty, monitoring, and existing local stack services.
  - Marketing agent is small: about 40 MiB RAM.
  - Local Ollama models are not kept loaded for the marketing agent.
- Nvidia-2 (`<NVIDIA2_HOST>`) is the intended model and creative worker.
  - Runs Ollama on `<APPROVED_PRIVATE_OLLAMA_URL>`.
  - Runs ComfyUI on `<APPROVED_PRIVATE_COMFYUI_URL>`.
  - Keeps `qwen3.6:35b` available for private marketing work.
  - `gemma4:31b` is kept on demand, not permanently warm.

## Marketing agent routing

The marketing agent reads these values from `deploy/marketing-agent.generated.env` on Nvidia-1:

```env
COMFYUI_BASE_URL=<APPROVED_PRIVATE_COMFYUI_URL>
OLLAMA_BASE_URL=<APPROVED_PRIVATE_OLLAMA_URL>
LOCAL_OPENAI_BASE_URL=<APPROVED_PRIVATE_OPENAI_COMPATIBLE_URL>
LOCAL_OPENAI_API_KEY=ollama
LOCAL_MODEL_NAME=qwen3.6:35b
```

Do not put real API keys in `.env.example` files.

## Why

Nvidia-1 previously had both `qwen3.6:35b` and `gemma4:31b` loaded with `262144` context and `Forever` keep-alive. That pinned a large amount of unified memory and filled swap. Routing the marketing agent to Nvidia-2 prevents it from reloading those large model sessions on Nvidia-1.

## Checks

Run these from the project root on Nvidia-1:

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:8117 \
  --access-token-file deploy/secrets/marketing_mutation_token
```

Run these from any host with SSH access:

```bash
ssh "$WAMOCON_NVIDIA1_SSH_HOST" "free -h; ollama ps"
ssh "$WAMOCON_NVIDIA2_SSH_HOST" "free -h; ollama ps"
```

Load both SSH aliases from the protected service catalog. Do not commit concrete
hostnames or private addresses to this public repository.
