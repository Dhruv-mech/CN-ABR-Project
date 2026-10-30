"""MPEG-DASH Video Encoding Module.

Prepares multi-bitrate H.264 / AAC video representations and generates a valid
MPEG-DASH MPD manifest along with initialization and media segment chunks (.m4s).

Key Features:
- Probes source video using ffprobe to detect resolution, frame rate, duration, and codecs.
- Automatically selects a representation ladder (360p, 480p, 720p, 1080p) without upscaling.
- Enforces strict GOP and keyframe alignment across all video streams for seamless bitrate switching.
- Uses standard 2.0-second chunk segmentation matching simulation configuration.
- Executes via Windows-compatible subprocess argument lists (no shell string concatenation).
- Verifies manifest and segment presence on disk.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union


@dataclass
class VideoMetadata:
    """Probed metadata describing the source video file."""
    width: int
    height: int
    duration_sec: float
    fps: float
    video_codec: str
    has_audio: bool
    audio_codec: Optional[str] = None
    bitrate_bps: Optional[int] = None

    @property
    def resolution_str(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass
class Representation:
    """A single video quality tier in the DASH adaptation ladder."""
    name: str
    width: int
    height: int
    video_bitrate_kbps: int
    maxrate_kbps: int
    bufsize_kbps: int

    @property
    def resolution_str(self) -> str:
        return f"{self.width}x{self.height}"


DEFAULT_CANDIDATE_LADDER: List[Representation] = [
    Representation("360p", 640, 360, 400, 440, 800),
    Representation("480p", 854, 480, 800, 880, 1600),
    Representation("720p", 1280, 720, 1500, 1650, 3000),
    Representation("1080p", 1920, 1080, 3000, 3300, 6000),
]


def find_executable(name: str) -> Optional[str]:
    """
    Locates an executable binary on PATH or standard Windows install locations.

    Args:
        name: Binary name without extension (e.g. 'ffmpeg', 'ffprobe').

    Returns:
        Optional[str]: Absolute path to executable if found, otherwise None.
    """
    # 1. Check standard PATH
    found = shutil.which(name)
    if found:
        return str(Path(found).resolve())

    # 2. Check common Windows installation paths
    candidates = [
        Path(r"C:\ffmpeg\bin") / f"{name}.exe",
        Path(r"C:\Program Files\ffmpeg\bin") / f"{name}.exe",
        Path(r"C:\Program Files (x86)\ffmpeg\bin") / f"{name}.exe",
        Path(r"C:\tools\ffmpeg\bin") / f"{name}.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    # 3. Check User PATH environment entries if not yet propagated
    user_path = os.environ.get("Path", "")
    for p in user_path.split(os.pathsep):
        if p.strip():
            candidate = Path(p.strip()) / f"{name}.exe"
            if candidate.is_file():
                return str(candidate.resolve())

    return None


def probe_video(video_path: Union[str, Path], ffprobe_bin: Optional[str] = None) -> VideoMetadata:
    """
    Inspects source video using ffprobe and extracts technical stream properties.

    Args:
        video_path: Path to the input video file.
        ffprobe_bin: Optional path to ffprobe binary.

    Returns:
        VideoMetadata: Technical parameters of video and audio streams.

    Raises:
        FileNotFoundError: If input file or ffprobe binary does not exist.
        ValueError: If file contains no valid video stream or probing fails.
    """
    path = Path(video_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Source video file not found: '{path}'")

    probe_exe = ffprobe_bin or find_executable("ffprobe")
    if not probe_exe:
        raise FileNotFoundError(
            "ffprobe executable not found. Ensure FFmpeg is installed and added to PATH "
            "(or located in C:\\ffmpeg\\bin\\)."
        )

    cmd = [
        probe_exe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as e:
        raise RuntimeError(f"Failed to execute ffprobe: {e}") from e

    if proc.returncode != 0:
        raise ValueError(f"ffprobe exited with error (code {proc.returncode}):\n{proc.stderr.strip()}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ValueError(f"ffprobe returned invalid JSON output: {e}") from e

    streams = data.get("streams", [])
    video_stream = None
    audio_stream = None

    for s in streams:
        if s.get("codec_type") == "video" and video_stream is None:
            video_stream = s
        elif s.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = s

    if not video_stream:
        raise ValueError(f"No video stream found in media file: '{path}'")

    # Parse dimensions
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid video resolution probed: {width}x{height}")

    # Parse frame rate
    fps_raw = video_stream.get("r_frame_rate", video_stream.get("avg_frame_rate", "30/1"))
    try:
        fps_frac = Fraction(fps_raw)
        fps = float(fps_frac) if fps_frac.denominator != 0 else 30.0
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    # Parse duration
    format_info = data.get("format", {})
    duration_str = video_stream.get("duration", format_info.get("duration", "0"))
    try:
        duration_sec = float(duration_str)
    except ValueError:
        duration_sec = 0.0

    # Parse bit rate
    bitrate_str = format_info.get("bit_rate", video_stream.get("bit_rate"))
    bitrate_bps = int(bitrate_str) if bitrate_str and bitrate_str.isdigit() else None

    return VideoMetadata(
        width=width,
        height=height,
        duration_sec=duration_sec,
        fps=fps,
        video_codec=video_stream.get("codec_name", "unknown"),
        has_audio=audio_stream is not None,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        bitrate_bps=bitrate_bps,
    )


def select_representation_ladder(
    source_width: int,
    source_height: int,
    candidate_ladder: Optional[List[Representation]] = None,
) -> List[Representation]:
    """
    Selects valid DASH representations without upscaling beyond source dimensions.

    Args:
        source_width: Native width of the source video in pixels.
        source_height: Native height of the source video in pixels.
        candidate_ladder: Optional list of Representation tiers to consider.

    Returns:
        List[Representation]: Filtered representations that fit within source dimensions.
    """
    candidates = candidate_ladder or DEFAULT_CANDIDATE_LADDER
    # Filter out representations exceeding source height or width
    valid = [
        rep for rep in candidates
        if rep.height <= source_height and rep.width <= source_width
    ]

    # Fallback: if source is smaller than lowest tier (e.g. 240p), create a single tier at source res
    if not valid:
        valid = [
            Representation(
                name=f"{source_height}p",
                width=source_width,
                height=source_height,
                video_bitrate_kbps=300,
                maxrate_kbps=330,
                bufsize_kbps=600,
            )
        ]

    return valid


def build_ffmpeg_dash_command(
    input_path: Union[str, Path],
    manifest_name: str,
    representations: List[Representation],
    has_audio: bool,
    segment_duration_sec: float = 2.0,
    fps: float = 60.0,
    preset: str = "veryfast",
    audio_bitrate_kbps: int = 128,
    ffmpeg_bin: Optional[str] = None,
) -> List[str]:
    """
    Constructs the argument list for FFmpeg to produce multi-representation DASH streams.

    Enforces:
    - Independent stream scaling and bitrate targeting for each representation.
    - Closed GOP with identical GOP size across all streams for aligned keyframes.
    - 2.0-second chunk segmentation.
    - Separate video and audio AdaptationSets in the MPD manifest.

    Args:
        input_path: Absolute path to the source video file.
        manifest_name: Manifest filename (e.g. 'stream.mpd').
        representations: Selected video representations to encode.
        has_audio: Whether input video contains an audio track.
        segment_duration_sec: Segment length in seconds.
        fps: Video frame rate.
        preset: x264 encoding preset.
        audio_bitrate_kbps: Audio bitrate in kbps.
        ffmpeg_bin: Optional path to ffmpeg binary.

    Returns:
        List[str]: Windows-compatible argument list for subprocess.
    """
    ff_bin = ffmpeg_bin or find_executable("ffmpeg") or "ffmpeg"
    abs_input = str(Path(input_path).resolve())

    # Exact keyframe interval (GOP size) to match segment duration
    gop_size = max(1, int(round(fps * segment_duration_sec)))

    cmd: List[str] = [
        ff_bin,
        "-y",
        "-i", abs_input,
    ]

    # Map video streams for each representation
    for i, rep in enumerate(representations):
        cmd.extend([
            "-map", "0:v:0",
            f"-s:v:{i}", f"{rep.width}x{rep.height}",
            f"-b:v:{i}", f"{rep.video_bitrate_kbps}k",
            f"-maxrate:v:{i}", f"{rep.maxrate_kbps}k",
            f"-bufsize:v:{i}", f"{rep.bufsize_kbps}k",
        ])

    # Global video encoding parameters
    cmd.extend([
        "-c:v", "libx264",
        "-preset", preset,
        "-g", str(gop_size),
        "-keyint_min", str(gop_size),
        "-sc_threshold", "0",
    ])

    # Audio mapping and encoding (if audio present)
    if has_audio:
        cmd.extend([
            "-map", "0:a:0?",
            "-c:a", "aac",
            "-b:a", f"{audio_bitrate_kbps}k",
            "-ar", "48000",
            "-adaptation_sets", "id=0,streams=v id=1,streams=a",
        ])
    else:
        cmd.extend([
            "-adaptation_sets", "id=0,streams=v",
        ])

    # DASH muxer options
    cmd.extend([
        "-f", "dash",
        "-seg_duration", str(segment_duration_sec),
        "-use_template", "1",
        "-use_timeline", "1",
        "-init_seg_name", "init-stream$RepresentationID$.m4s",
        "-media_seg_name", "chunk-stream$RepresentationID$-$Number%05d$.m4s",
        manifest_name,
    ])

    return cmd


def verify_dash_output(
    output_dir: Union[str, Path],
    manifest_name: str = "stream.mpd",
) -> Dict[str, Any]:
    """
    Validates that the DASH manifest and referenced initialization / media segments exist on disk.

    Args:
        output_dir: Directory where DASH files were generated.
        manifest_name: Filename of the MPD manifest.

    Returns:
        Dict[str, Any]: Verification summary detailing parsed representations and segment files.

    Raises:
        FileNotFoundError: If manifest or required segments are missing.
        ValueError: If manifest XML is corrupted or has no representations.
    """
    out_path = Path(output_dir).resolve()
    manifest_file = out_path / manifest_name

    if not manifest_file.is_file():
        raise FileNotFoundError(f"DASH manifest not found: '{manifest_file}'")

    try:
        tree = ET.parse(manifest_file)
        root = tree.getroot()
    except Exception as e:
        raise ValueError(f"Failed to parse DASH manifest XML: {e}") from e

    # Namespace handling
    ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}

    # Extract representations
    rep_elements = root.findall(".//mpd:Representation", ns)
    if not rep_elements:
        # Fallback if no namespace prefix used
        rep_elements = root.findall(".//{urn:mpeg:dash:schema:mpd:2011}Representation")
    if not rep_elements:
        rep_elements = [el for el in root.iter() if el.tag.endswith("Representation")]

    if not rep_elements:
        raise ValueError(f"No <Representation> elements found in '{manifest_file}'")

    parsed_reps = []
    missing_init_segments = []

    for rep in rep_elements:
        rep_id = rep.get("id")
        mime = rep.get("mimeType", "")
        bandwidth = rep.get("bandwidth", "0")
        width = rep.get("width")
        height = rep.get("height")

        parsed_reps.append({
            "id": rep_id,
            "mime_type": mime,
            "bandwidth_bps": int(bandwidth),
            "width": int(width) if width else None,
            "height": int(height) if height else None,
        })

        # Expected init segment for this representation
        expected_init = out_path / f"init-stream{rep_id}.m4s"
        if not expected_init.is_file():
            missing_init_segments.append(expected_init.name)

    if missing_init_segments:
        raise FileNotFoundError(f"Missing initialization segment(s): {missing_init_segments}")

    # Discover generated chunk files
    chunk_files = sorted(list(out_path.glob("chunk-stream*.m4s")))
    if not chunk_files:
        raise FileNotFoundError(f"No media segment chunks (*.m4s) found in '{out_path}'")

    init_files = sorted(list(out_path.glob("init-stream*.m4s")))

    return {
        "manifest_path": manifest_file,
        "manifest_name": manifest_name,
        "representations_count": len(parsed_reps),
        "representations": parsed_reps,
        "init_segments_count": len(init_files),
        "init_segments": [f.name for f in init_files],
        "media_segments_count": len(chunk_files),
        "total_files": len(list(out_path.glob("*"))),
        "valid": True,
    }


def encode_to_dash(
    input_path: Union[str, Path],
    output_dir: Union[str, Path] = "static/dash",
    segment_duration_sec: float = 2.0,
    preset: str = "veryfast",
    manifest_name: str = "stream.mpd",
    ffmpeg_bin: Optional[str] = None,
    ffprobe_bin: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the full DASH encoding pipeline:
    1. Probes source video dimensions, frame rate, duration, and audio.
    2. Selects an appropriate non-upscaling representation ladder.
    3. Builds and executes the FFmpeg command within the target output directory.
    4. Validates the generated manifest and segment chunks on disk.

    Args:
        input_path: Path to source video file (e.g. 'media/input.mp4').
        output_dir: Target directory for manifest and media segments.
        segment_duration_sec: Chunk duration in seconds (default: 2.0).
        preset: FFmpeg x264 preset (e.g. 'veryfast').
        manifest_name: Name of generated MPD file (default: 'stream.mpd').
        ffmpeg_bin: Optional path to ffmpeg executable.
        ffprobe_bin: Optional path to ffprobe executable.

    Returns:
        Dict[str, Any]: Pipeline outcome summary and verification details.

    Raises:
        FileNotFoundError: If input video or FFmpeg binaries are missing.
        RuntimeError: If FFmpeg encoding terminates with an error code.
    """
    src_path = Path(input_path).resolve()
    out_dir = Path(output_dir).resolve()

    # Step 1: Probe source
    metadata = probe_video(src_path, ffprobe_bin=ffprobe_bin)

    # Step 2: Select representation ladder
    representations = select_representation_ladder(
        source_width=metadata.width,
        source_height=metadata.height,
    )

    # Step 3: Ensure output directory exists
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 4: Construct FFmpeg command
    cmd = build_ffmpeg_dash_command(
        input_path=src_path,
        manifest_name=manifest_name,
        representations=representations,
        has_audio=metadata.has_audio,
        segment_duration_sec=segment_duration_sec,
        fps=metadata.fps,
        preset=preset,
        ffmpeg_bin=ffmpeg_bin,
    )

    # Step 5: Execute encoding in output directory
    proc = subprocess.run(
        cmd,
        cwd=out_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(
            f"FFmpeg DASH encoding failed with exit code {proc.returncode}:\n{err_msg}"
        )

    # Step 6: Verify output artifacts
    verification = verify_dash_output(out_dir, manifest_name=manifest_name)

    return {
        "source_metadata": metadata,
        "selected_representations": representations,
        "output_directory": out_dir,
        "manifest_path": verification["manifest_path"],
        "representations_count": verification["representations_count"],
        "init_segments_count": verification["init_segments_count"],
        "media_segments_count": verification["media_segments_count"],
        "verification": verification,
        "success": True,
    }


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments for the DASH encoder."""
    parser = argparse.ArgumentParser(
        description="Encode video into multi-bitrate MPEG-DASH stream using FFmpeg.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        default="media/input.mp4",
        help="Path to source video file.",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="static/dash",
        help="Output directory for MPD manifest and segments.",
    )
    parser.add_argument(
        "-s", "--segment-duration",
        type=float,
        default=2.0,
        help="Duration of each DASH segment in seconds.",
    )
    parser.add_argument(
        "-p", "--preset",
        type=str,
        default="veryfast",
        help="FFmpeg x264 encoding preset (ultrafast, superfast, veryfast, faster, fast, medium).",
    )
    parser.add_argument(
        "--manifest-name",
        type=str,
        default="stream.mpd",
        help="Name of the generated MPD manifest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe source and display planned command without executing FFmpeg.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()

    print("\n" + "=" * 60)
    print("             MPEG-DASH VIDEO ENCODER")
    print("=" * 60)
    print(f"  Source Video      : {input_path}")
    print(f"  Target Directory  : {output_dir}")
    print(f"  Segment Duration  : {args.segment_duration}s")
    print(f"  Encoding Preset   : {args.preset}")
    print("-" * 60)

    try:
        # Check source exists
        if not input_path.is_file():
            print(f"Error: Source video file not found at '{input_path}'", file=sys.stderr)
            return 1

        # Probe video
        meta = probe_video(input_path)
        print(f"  Source Resolution : {meta.resolution_str}")
        print(f"  Frame Rate        : {meta.fps:.2f} fps")
        print(f"  Duration          : {meta.duration_sec:.2f} seconds")
        print(f"  Video Codec       : {meta.video_codec}")
        print(f"  Has Audio Track   : {meta.has_audio} ({meta.audio_codec or 'None'})")

        # Ladder selection
        ladder = select_representation_ladder(meta.width, meta.height)
        print(f"\n  Selected Representations ({len(ladder)} tiers):")
        for rep in ladder:
            print(f"    - [{rep.name:<5}] {rep.resolution_str:<10} @ {rep.video_bitrate_kbps} kbps")

        if meta.has_audio:
            print("    - [Audio] 48kHz Stereo AAC @ 128 kbps")

        cmd = build_ffmpeg_dash_command(
            input_path=input_path,
            manifest_name=args.manifest_name,
            representations=ladder,
            has_audio=meta.has_audio,
            segment_duration_sec=args.segment_duration,
            fps=meta.fps,
            preset=args.preset,
        )

        if args.dry_run:
            print("\n--- Dry Run: Planned FFmpeg Command ---")
            print(" ".join(cmd))
            print("---------------------------------------")
            return 0

        print("\n--- Encoding Source Video to MPEG-DASH ---")
        print("Executing FFmpeg (this may take a few moments)...")
        result = encode_to_dash(
            input_path=input_path,
            output_dir=output_dir,
            segment_duration_sec=args.segment_duration,
            preset=args.preset,
            manifest_name=args.manifest_name,
        )

        print("\n============================================================")
        print("               DASH ENCODING COMPLETE")
        print("============================================================")
        print(f"  Manifest File          : {result['manifest_path']}")
        print(f"  Video Representations  : {len(ladder)}")
        print(f"  Init Segments Generated: {result['init_segments_count']}")
        print(f"  Media Chunks Generated : {result['media_segments_count']}")
        print(f"  Verification Status    : PASSED (All referenced files present)")
        print("============================================================\n")
        return 0

    except Exception as e:
        print(f"\nEncoding error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
