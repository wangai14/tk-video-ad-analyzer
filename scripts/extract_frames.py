"""
视频帧提取脚本 - 智能提取视频关键帧 + 音频
Usage:
  python extract_frames.py <video_path> [--output <output_dir>] [--scene-threshold <0.0-1.0>] [--max-frames <num>]
"""

import argparse
import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def check_binary(binary_name: str) -> bool:
    """检查外部二进制是否可用。"""
    try:
        subprocess.run([binary_name, "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def parse_frame_rate(frame_rate: str) -> float:
    """安全解析 ffprobe 返回的帧率字符串。"""
    if not frame_rate:
        return 0.0
    try:
        return float(Fraction(frame_rate))
    except (ValueError, ZeroDivisionError):
        return 0.0


def get_video_info(video_path: Path) -> Optional[Dict]:
    """获取视频基本信息。"""
    probe_cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    try:
        result = subprocess.run(probe_cmd, capture_output=True, encoding='utf-8', errors='replace', check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def get_first_stream(info: Dict, codec_type: str) -> Dict:
    streams = info.get("streams", []) if isinstance(info, dict) else []
    for stream in streams:
        if stream.get("codec_type") == codec_type:
            return stream
    return {}


def extract_pts_times(stderr_output: str) -> List[float]:
    """从 ffmpeg showinfo 输出中提取时间戳。"""
    matches = re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr_output or "")
    return [float(item) for item in matches]


def select_evenly(items: Sequence[Tuple[Path, Optional[float]]], max_items: int) -> List[Tuple[Path, Optional[float]]]:
    if max_items <= 0 or not items:
        return []
    if max_items == 1:
        return [items[0]]
    if len(items) <= max_items:
        return list(items)

    selected: List[Tuple[Path, Optional[float]]] = []
    step = (len(items) - 1) / (max_items - 1)
    seen_indexes = set()
    for i in range(max_items):
        index = round(i * step)
        if index in seen_indexes:
            continue
        seen_indexes.add(index)
        selected.append(items[index])

    while len(selected) < max_items:
        for index, item in enumerate(items):
            if index not in seen_indexes:
                seen_indexes.add(index)
                selected.append(item)
                if len(selected) == max_items:
                    break

    return selected[:max_items]


def normalize_output_names(
    output_dir: Path,
    extracted_items: Sequence[Tuple[Path, Optional[float]]],
) -> List[str]:
    """统一关键帧命名格式。"""
    normalized_paths: List[str] = []
    for index, (source_path, timestamp) in enumerate(extracted_items):
        if timestamp is None:
            target_name = f"frame_{index:03d}.jpg"
        else:
            target_name = f"frame_{index:03d}_{timestamp:.1f}s.jpg"

        target_path = output_dir / target_name
        if source_path != target_path:
            if target_path.exists():
                target_path.unlink()
            source_path.rename(target_path)
        normalized_paths.append(str(target_path))

    return normalized_paths


def extract_frames_scene_based(
    video_path: Path,
    output_dir: Path,
    threshold: float = 0.3,
    max_frames: int = 15,
) -> List[str]:
    """基于场景变化检测提取关键帧，并尽量保留时间戳。"""
    temp_pattern = output_dir / "_scene_%03d.jpg"
    extract_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"select=gt(scene\\,{threshold}),scale=540:-1,showinfo",
        "-vsync",
        "vfr",
        str(temp_pattern),
    ]

    result = subprocess.run(extract_cmd, capture_output=True, encoding='utf-8', errors='replace', check=False)
    all_frames = sorted(output_dir.glob("_scene_*.jpg"))
    pts_times = extract_pts_times(result.stderr)

    paired_items: List[Tuple[Path, Optional[float]]] = []
    for idx, frame_file in enumerate(all_frames):
        timestamp = pts_times[idx] if idx < len(pts_times) else None
        paired_items.append((frame_file, timestamp))

    selected_items = select_evenly(paired_items, max_frames)
    selected_sources = {path for path, _ in selected_items}

    for frame_file in all_frames:
        if frame_file not in selected_sources and frame_file.exists():
            frame_file.unlink()

    return normalize_output_names(output_dir, selected_items)


def unique_timestamps(timestamps: Sequence[float], duration: float) -> List[float]:
    normalized: List[float] = []
    seen = set()
    max_duration = max(duration, 0.0)
    for value in timestamps:
        clipped = min(max(value, 0.0), max_duration)
        key = round(clipped, 2)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(clipped)
    return normalized


def extract_frames_time_based(
    video_path: Path,
    output_dir: Path,
    sample_fps: Optional[float] = None,
    max_frames: int = 15,
) -> List[str]:
    """基于固定关键时间点均匀提取关键帧。"""
    video_info = get_video_info(video_path)
    if not video_info:
        return []

    duration = float(video_info.get("format", {}).get("duration", 0) or 0)
    if duration <= 0:
        return []

    if sample_fps and sample_fps > 0:
        raw_timestamps = [index / sample_fps for index in range(int(duration * sample_fps) + 1)]
        raw_timestamps.append(duration * 0.98)
        timestamps = unique_timestamps(raw_timestamps, duration)
        if max_frames > 0 and len(timestamps) > max_frames:
            timestamp_items = [(Path(f"frame_{idx:03d}_{timestamp:.1f}s.jpg"), timestamp) for idx, timestamp in enumerate(timestamps)]
            timestamps = [timestamp for _, timestamp in select_evenly(timestamp_items, max_frames) if timestamp is not None]
    else:
        key_points = [0.0, 0.08, 0.18, 0.30, 0.45, 0.60, 0.75, 0.90, 0.98]
        timestamps = unique_timestamps([duration * ratio for ratio in key_points], duration)

    output_files: List[str] = []
    for index, timestamp in enumerate(timestamps):
        output_file = output_dir / f"frame_{index:03d}_{timestamp:.1f}s.jpg"
        extract_cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(output_file),
        ]
        subprocess.run(extract_cmd, capture_output=True, check=False)
        if output_file.exists():
            output_files.append(str(output_file))

    return output_files


def extract_audio(video_path: Path, output_dir: Path) -> Optional[str]:
    """提取音频轨道用于语言识别。"""
    audio_file = output_dir / "audio.wav"
    extract_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_file),
    ]

    try:
        subprocess.run(extract_cmd, capture_output=True, encoding='utf-8', errors='replace', check=True)
        if audio_file.exists():
            return str(audio_file)
    except subprocess.CalledProcessError:
        return None
    return None


def get_video_metadata(video_path: Path) -> Dict:
    """获取视频元数据。"""
    info = get_video_info(video_path)
    if not info:
        return {}

    video_stream = get_first_stream(info, "video")
    streams = info.get("streams", [])
    format_info = info.get("format", {})

    return {
        "duration": float(format_info.get("duration", 0) or 0),
        "size_bytes": int(format_info.get("size", 0) or 0),
        "width": int(video_stream.get("width", 0) or 0),
        "height": int(video_stream.get("height", 0) or 0),
        "codec": video_stream.get("codec_name", "unknown"),
        "fps": parse_frame_rate(video_stream.get("r_frame_rate", "0/1")),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="视频帧提取工具 - 智能关键帧 + 音频提取")
    parser.add_argument("video_path", help="视频文件路径")
    parser.add_argument("--output", "-o", default=None, help="输出目录（默认：视频同目录下的 temp_frames）")
    parser.add_argument(
        "--scene-threshold",
        "-t",
        type=float,
        default=0.3,
        help="场景变化阈值 0.0-1.0（越高越不敏感），默认 0.3",
    )
    parser.add_argument("--max-frames", "-m", type=int, default=15, help="最大提取帧数，默认 15")
    parser.add_argument("--no-scene", action="store_true", help="禁用场景检测，改用时间均匀采样")
    parser.add_argument("--fps", type=float, default=None, help="时间采样模式下的采样频率，配合 --max-frames 控制最终帧数")
    args = parser.parse_args()

    video_path = Path(args.video_path)
    if not video_path.exists():
        print(json.dumps({"status": "error", "message": f"Video file not found: {video_path}"}, ensure_ascii=False))
        sys.exit(1)

    missing_binaries = [name for name in ("ffmpeg", "ffprobe") if not check_binary(name)]
    if missing_binaries:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"Missing required binaries: {', '.join(missing_binaries)}",
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    output_dir = Path(args.output) if args.output else video_path.parent / "temp_frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = get_video_metadata(video_path)
    warnings: List[str] = []

    if args.no_scene:
        frames = extract_frames_time_based(video_path, output_dir, args.fps, args.max_frames)
    else:
        frames = extract_frames_scene_based(video_path, output_dir, args.scene_threshold, args.max_frames)
        if not frames:
            warnings.append("场景检测未提取到关键帧，已建议改用时间采样模式重试。")

    if not frames:
        frames = extract_frames_time_based(video_path, output_dir, args.fps, args.max_frames)
        if frames:
            warnings.append("已自动回退为时间采样模式。")

    audio_file = None
    if metadata.get("has_audio", False):
        audio_file = extract_audio(video_path, output_dir)
        if not audio_file:
            warnings.append("检测到音轨但音频提取失败。")

    result = {
        "status": "ok",
        "video_path": str(video_path),
        "output_dir": str(output_dir),
        "metadata": metadata,
        "frames_extracted": len(frames),
        "frame_files": frames,
        "audio_extracted": audio_file is not None,
        "audio_file": audio_file,
        "warnings": warnings,
    }

    result_path = output_dir / "extraction_result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
