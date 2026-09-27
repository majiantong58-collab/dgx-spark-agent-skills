#!/bin/bash
# 下载 Tier 1 本地 VLM：Qwen3-VL-2B-Instruct —— **hf-mirror 通道（备用，慢）**
#
# 目标路径：models/Qwen3-VL-2B-Instruct/model.safetensors   （4,255,140,312 B ≈ 4.0 GB）
# 磁盘要求：预留 ≥ 5 GB
# 用法：    bash scripts/fetch.sh
#
# 🔴 **速度警告（实测，非估计）**
#   本通道实测吞吐仅 **约 9–66 KB/s**（5.35 MB 的 YOLO 权重耗时 82.7 s ≈ 66 KB/s；
#   大文件采样时多次掉到 0 B/s）。按此速度，4.0 GB 需要 **约 18 小时以上**，
#   且中途频繁超时。**正常情况请用 `scripts/fetch_ms.sh`（ModelScope，实测约 30 MB/s，
#   2.5 分钟下完）。** 本脚本仅在 ModelScope 不可用时作为兜底。
#
# 特性：断点续传（`curl -C -`），每轮最多 300 次重试，进度写 models/download.log。
#
# ⚠️ 权重不入库（`.gitignore` 排除 models/），新克隆的仓库需先下载。

set -u

cd "$(dirname "$0")/.." || exit 1

URL="https://hf-mirror.com/Qwen/Qwen3-VL-2B-Instruct/resolve/main/model.safetensors"
OUT="models/Qwen3-VL-2B-Instruct/model.safetensors"
LOG="models/download.log"
TARGET=4255140312

mkdir -p "$(dirname "$OUT")" models

echo "🔴 注意：hf-mirror 通道实测约 9–66 KB/s，4 GB 预计需 18 小时以上。" >&2
echo "   推荐改用：bash scripts/fetch_ms.sh" >&2

for i in $(seq 1 300); do
  sz=$(stat -c%s "$OUT" 2>/dev/null || echo 0)
  echo "[$(date +%Y-%m-%d_%H:%M:%S)] attempt $i start size=$sz/$TARGET" >>"$LOG"
  if [ "$sz" -ge "$TARGET" ]; then
    echo "[$(date +%H:%M:%S)] DONE" >>"$LOG"
    echo "完成：$OUT"
    exit 0
  fi
  curl -L -C - --connect-timeout 20 --max-time 900 -o "$OUT" "$URL" 2>>"$LOG"
  sz2=$(stat -c%s "$OUT" 2>/dev/null || echo 0)
  echo "[$(date +%H:%M:%S)] attempt $i end size=$sz2" >>"$LOG"
  sleep 5
done
