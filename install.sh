#!/usr/bin/env bash
# tk-kit 安装脚本：装依赖 + 装机仓库内所有技能 + 自检
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SKILLS_DIR="$REPO_DIR/.agents/skills"
SKILL_DEST="${SKILL_DEST:-$HOME/.dsh/skills}"
KIT="$REPO_DIR/kit"

echo "==> 仓库目录: $REPO_DIR"

if [ ! -d "$SKILLS_DIR" ]; then
  echo "!! 找不到技能目录: $SKILLS_DIR" >&2
  exit 1
fi

echo "==> 安装 Python 依赖（yt-dlp + ffmpeg）"
cd "$KIT"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q yt-dlp imageio-ffmpeg

echo "==> 安装技能到 $SKILL_DEST"
mkdir -p "$SKILL_DEST"
for d in "$SKILLS_DIR"/*/; do
  name="$(basename "$d")"
  rm -rf "$SKILL_DEST/$name"
  cp -R "$d" "$SKILL_DEST/$name"
  echo "    + $name"
done

echo "==> 自检"
"$KIT/.venv/bin/yt-dlp" --version | sed 's/^/    yt-dlp: /'
"$KIT/.venv/bin/python" -c "import imageio_ffmpeg; print('    ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"
for d in "$SKILL_DEST"/*/; do
  name="$(basename "$d")"
  case "$name" in
    tk-*) [ -f "$d/SKILL.md" ] && echo "    技能: $d/SKILL.md" ;;
  esac
done

echo
echo "✅ 安装完成"
echo "   下一步：export KIT=$KIT"
echo "   代理默认 http://127.0.0.1:7890，可用 TK_PROXY 覆盖"
