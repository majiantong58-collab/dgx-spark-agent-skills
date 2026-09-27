#!/bin/bash
# 下载 Tier 1 本地 VLM：Qwen3-VL-2B-Instruct（**推荐通道**）
#
# 目标路径：models/Qwen3-VL-2B-Instruct/   （13 个文件，合计约 4.3 GB）
#           ↑ 与 docs/DELIVERY.md §5.1、bench_layers.py、local_tier_pipeline.py 一致
# 磁盘要求：预留 ≥ 5 GB
# 执行位置：**必须在项目根目录或任意位置均可**——脚本会自行定位仓库根
# 用法：    bash scripts/fetch_ms.sh
#
# 通道：ModelScope（国内直连）。**实测约 30 MB/s**，4.3 GB 约 2.5 分钟下完。
# 特性：逐文件下载，`curl -C -` 断点续传，失败自动重试（每文件最多 50 次），
#       进度写入 models/download_ms.log，可随时中断后再跑。
#
# ⚠️ 权重不入库（`.gitignore` 排除 models/，单文件 4 GB 超 GitHub 100 MB 上限），
#    因此**新克隆的仓库必须先跑本脚本**才能运行 Tier 1。

set -u

# 定位仓库根：本脚本位于 <repo>/scripts/ 下
cd "$(dirname "$0")/.." || exit 1

D="models/Qwen3-VL-2B-Instruct"
LOG="models/download_ms.log"
API="https://www.modelscope.cn/api/v1/models/Qwen/Qwen3-VL-2B-Instruct/repo"

mkdir -p "$D" models

# 仓库文件清单（含模型权重、config、tokenizer、chat template）
FILES=".gitattributes README.md chat_template.json config.json configuration.json \
generation_config.json merges.txt model.safetensors preprocessor_config.json \
tokenizer.json tokenizer_config.json video_preprocessor_config.json vocab.json"

for f in $FILES; do
  for i in $(seq 1 50); do
    sz=$(stat -c%s "$D/$f" 2>/dev/null || echo 0)
    echo "[$(date +%H:%M:%S)] $f attempt $i size=$sz" >>"$LOG"
    curl -sL -C - --connect-timeout 20 --max-time 1800 \
      -o "$D/$f" "$API?Revision=master&FilePath=$f" && break
    sleep 3
  done
  # 小文件可能返回错误页，体积过小则视为失败
  if [ "$f" != "model.safetensors" ] && [ "${sz:-0}" -lt 10 ]; then
    echo "[$(date +%H:%M:%S)] WARN $f 体积异常，请人工核对" >>"$LOG"
  fi
done

echo "[$(date +%H:%M:%S)] ALL DONE" >>"$LOG"
echo "完成。目标目录：$D"
du -sh "$D" 2>/dev/null
