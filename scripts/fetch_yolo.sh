#!/bin/bash
# 下载 Tier 0 检测器权重：YOLO11n（COCO 预训练）
#
# 目标路径：models/yolo11n.pt   （单文件 5,613,764 B ≈ 5.4 MB）
# 磁盘要求：< 10 MB
# 用法：    bash scripts/fetch_yolo.sh
#
# 通道：hf-mirror.com 的 Ultralytics/YOLO11 仓库。
# ⚠️ **不要**从 GitHub Releases 取——实测本机到 github.com 的 release 资产
#    持续超时（3/3 次 000，约 21 s 断），而 hf-mirror 可正常获取。
#
# 校验（下载后应完全一致）：
#     md5 = 261474e91b15f5ef14a63c21ce6c0cbb
#
# ⚠️ 权重不入库（`.gitignore` 排除 models/），新克隆的仓库需先跑本脚本。

set -u

cd "$(dirname "$0")/.." || exit 1

URL="https://hf-mirror.com/Ultralytics/YOLO11/resolve/main/yolo11n.pt"
OUT="models/yolo11n.pt"
EXPECT_MD5="261474e91b15f5ef14a63c21ce6c0cbb"

mkdir -p models

for i in $(seq 1 10); do
  curl -L -C - --connect-timeout 20 --max-time 300 -o "$OUT" "$URL" && break
  echo "重试 $i ..." >&2
  sleep 5
done

if [ ! -s "$OUT" ]; then
  echo "下载失败：$OUT 为空" >&2
  exit 1
fi

got=$(md5sum "$OUT" | awk '{print $1}')
echo "md5 = $got"
if [ "$got" = "$EXPECT_MD5" ]; then
  echo "校验通过：$OUT"
else
  echo "⚠️ md5 与预期不符（预期 $EXPECT_MD5）——文件可能不完整，请重跑" >&2
  exit 1
fi
