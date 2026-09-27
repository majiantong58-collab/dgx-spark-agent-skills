#!/bin/bash
# 下载 SmolVLM-500M-Instruct —— **备用候选，当前无任何代码使用（保留仅供将来替换 Tier 1）**
#
# 目标路径：models/SmolVLM-500M-Instruct/   （model.safetensors 1,015,025,832 B ≈ 1.0 GB
#                                            + 8 个小文件）
# 磁盘要求：预留 ≥ 1.5 GB
# 用法：    bash scripts/fetch_smol.sh
#
# 🔴 **本脚本当前不是「快速开始」的一部分。**
#   仓库里没有任何代码加载 SmolVLM——`local_tier_pipeline.py` 用的是
#   Qwen3-VL-2B（见 `scripts/fetch_ms.sh`）。本脚本是探索更小模型时留下的备用通道，
#   **若不确定是否需要，请不要跑它。**
#
# 🔴 **速度警告（实测）**：hf-mirror 通道约 11 KB/s，1.0 GB 预计需 **约 26 小时**。
#   ModelScope 上**没有**该模型（已探测，404），故无快速通道可用。
#   若将来要正式采用 SmolVLM，应先寻找更快的镜像。
#
# 特性：断点续传（`curl -C -`），进度写 models/download_smol.log。

set -u

cd "$(dirname "$0")/.." || exit 1

B="https://hf-mirror.com/HuggingFaceTB/SmolVLM-500M-Instruct/resolve/main"
D="models/SmolVLM-500M-Instruct"
LOG="models/download_smol.log"

mkdir -p "$D" models

echo "🔴 注意：本模型当前无人使用，且 hf-mirror 通道约 11 KB/s（1 GB 约 26 小时）。" >&2
echo "   Tier 1 请改用：bash scripts/fetch_ms.sh" >&2

# 权重：断点续传 + 重试
sz=$(stat -c%s "$D/model.safetensors" 2>/dev/null || echo 0)
for i in $(seq 1 300); do
  sz=$(stat -c%s "$D/model.safetensors" 2>/dev/null || echo 0)
  [ "$sz" -ge 1015025832 ] && { echo "[$(date +%H:%M:%S)] OK model.safetensors" >>"$LOG"; break; }
  echo "[$(date +%H:%M:%S)] model.safetensors attempt $i size=$sz" >>"$LOG"
  curl -L -C - --connect-timeout 20 --max-time 900 \
    -o "$D/model.safetensors" "$B/model.safetensors" 2>>"$LOG"
  sleep 5
done

# 配套的小文件（config / processor / tokenizer / chat template）
for f in config.json processor_config.json tokenizer.json tokenizer_config.json \
         special_tokens_map.json chat_template.json preprocessor_config.json \
         generation_config.json; do
  curl -sL -C - --connect-timeout 20 --max-time 120 -o "$D/$f" "$B/$f" 2>>"$LOG"
done

echo "[$(date +%H:%M:%S)] ALL DONE" >>"$LOG"
echo "完成。目标目录：$D"
