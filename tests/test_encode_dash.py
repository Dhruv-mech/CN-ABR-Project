"""Unit tests for Stage 7: Real DASH Video Encoding.

Verifies:
1. Executable discovery and error handling.
2. Source video validation and ffprobe inspection (with mocking).
3. Representation ladder filtering and anti-upscaling constraints.
4. FFmpeg DASH command construction and keyframe alignment.
5. Error handling for missing files and failed subprocess execution.
6. Manifest parsing and segment artifact verification.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.media.encode_dash import (
    VideoMetadata,
    Representation,
    find_executable,
    probe_video,
    select_representation_ladder,
    build_ffmpeg_dash_command,
    encode_to_dash,
    verify_dash_output,
    DEFAULT_CANDIDATE_LADDER,
)


class TestBinaryDiscovery(unittest.TestCase):
    """Tests executable location logic for FFmpeg tools."""

    def test_find_executable_nonexistent(self):
        """Verifies None is returned for an imaginary binary."""
        self.assertIsNone(find_executable("completely_nonexistent_binary_xyz_12345"))

    def test_find_executable_ffmpeg(self):
        """Verifies finding ffmpeg executable on this Windows test machine."""
        ff = find_executable("ffmpeg")
        self.assertIsNotNone(ff)
        self.assertTrue(Path(ff).is_file())


class TestSourceValidationAndProbing(unittest.TestCase):
    """Tests source file checking and ffprobe metadata extraction."""

    def test_probe_missing_file_raises_not_found(self):
        """Verifies FileNotFoundError on non-existent input video."""
        with self.assertRaises(FileNotFoundError):
            probe_video("nonexistent_video_path_abc.mp4")

    @patch("subprocess.run")
    def test_probe_video_mocked_success(self, mock_run):
        """Verifies metadata extraction from valid ffprobe JSON output."""
        mock_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "60/1",
                    "duration": "30.000000",
                    "bit_rate": "3500000",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                },
            ],
            "format": {
                "duration": "30.000000",
                "bit_rate": "3640000",
            },
        }

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(mock_output)
        mock_run.return_value = mock_proc

        # Create temporary dummy file to satisfy file existence check
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            temp_path = tf.name

        try:
            meta = probe_video(temp_path, ffprobe_bin="mock_ffprobe")
            self.assertEqual(meta.width, 1920)
            self.assertEqual(meta.height, 1080)
            self.assertEqual(meta.fps, 60.0)
            self.assertAlmostEqual(meta.duration_sec, 30.0)
            self.assertEqual(meta.video_codec, "h264")
            self.assertTrue(meta.has_audio)
            self.assertEqual(meta.audio_codec, "aac")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("subprocess.run")
    def test_probe_video_no_video_stream(self, mock_run):
        """Verifies ValueError when media file contains no video stream."""
        mock_output = {
            "streams": [
                {"codec_type": "audio", "codec_name": "mp3"}
            ],
            "format": {},
        }
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(mock_output)
        mock_run.return_value = mock_proc

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
            temp_path = tf.name

        try:
            with self.assertRaises(ValueError) as ctx:
                probe_video(temp_path, ffprobe_bin="mock_ffprobe")
            self.assertIn("No video stream found", str(ctx.exception))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("subprocess.run")
    def test_probe_video_ffprobe_error(self, mock_run):
        """Verifies ValueError when ffprobe command fails with non-zero exit."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "Invalid data found when processing input"
        mock_run.return_value = mock_proc

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            temp_path = tf.name

        try:
            with self.assertRaises(ValueError) as ctx:
                probe_video(temp_path, ffprobe_bin="mock_ffprobe")
            self.assertIn("ffprobe exited with error", str(ctx.exception))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestResolutionLadderSelection(unittest.TestCase):
    """Tests anti-upscaling rules and resolution ladder filtering."""

    def test_1080p_source_selects_all_four_tiers(self):
        """1080p source (1920x1080) must select 360p, 480p, 720p, and 1080p."""
        ladder = select_representation_ladder(1920, 1080)
        self.assertEqual(len(ladder), 4)
        names = [r.name for r in ladder]
        self.assertEqual(names, ["360p", "480p", "720p", "1080p"])

    def test_720p_source_omits_1080p(self):
        """720p source (1280x720) must omit 1080p without upscaling."""
        ladder = select_representation_ladder(1280, 720)
        self.assertEqual(len(ladder), 3)
        names = [r.name for r in ladder]
        self.assertEqual(names, ["360p", "480p", "720p"])
        self.assertNotIn("1080p", names)

    def test_480p_source_omits_720p_and_1080p(self):
        """480p source (854x480) must omit 720p and 1080p."""
        ladder = select_representation_ladder(854, 480)
        self.assertEqual(len(ladder), 2)
        names = [r.name for r in ladder]
        self.assertEqual(names, ["360p", "480p"])

    def test_sub_360p_source_creates_fallback(self):
        """Source smaller than 360p (e.g. 320x240) must fallback to source resolution."""
        ladder = select_representation_ladder(320, 240)
        self.assertEqual(len(ladder), 1)
        self.assertEqual(ladder[0].width, 320)
        self.assertEqual(ladder[0].height, 240)


class TestFFmpegCommandConstruction(unittest.TestCase):
    """Tests FFmpeg argument generation, GOP size calculation, and DASH options."""

    def test_command_parameters_with_audio(self):
        """Verifies command arguments for multi-representation DASH with audio."""
        reps = [
            Representation("360p", 640, 360, 400, 440, 800),
            Representation("720p", 1280, 720, 1500, 1650, 3000),
        ]
        cmd = build_ffmpeg_dash_command(
            input_path="media/input.mp4",
            manifest_name="stream.mpd",
            representations=reps,
            has_audio=True,
            segment_duration_sec=2.0,
            fps=60.0,
            preset="veryfast",
            ffmpeg_bin="ffmpeg",
        )

        # Basic command structure
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("-y", cmd)
        self.assertIn("-i", cmd)

        # Representations scaling and bitrates
        self.assertIn("-s:v:0", cmd)
        self.assertIn("640x360", cmd)
        self.assertIn("-b:v:0", cmd)
        self.assertIn("400k", cmd)

        self.assertIn("-s:v:1", cmd)
        self.assertIn("1280x720", cmd)
        self.assertIn("-b:v:1", cmd)
        self.assertIn("1500k", cmd)

        # GOP calculation: 60 fps * 2.0s = 120 frames
        idx_g = cmd.index("-g")
        self.assertEqual(cmd[idx_g + 1], "120")
        idx_key = cmd.index("-keyint_min")
        self.assertEqual(cmd[idx_key + 1], "120")
        self.assertIn("-sc_threshold", cmd)

        # Audio and adaptation sets
        self.assertIn("-adaptation_sets", cmd)
        adapt_idx = cmd.index("-adaptation_sets")
        self.assertEqual(cmd[adapt_idx + 1], "id=0,streams=v id=1,streams=a")

        # DASH muxer options
        self.assertIn("-f", cmd)
        self.assertIn("dash", cmd)
        self.assertIn("-seg_duration", cmd)
        self.assertIn("2.0", cmd)
        self.assertEqual(cmd[-1], "stream.mpd")

    def test_command_parameters_without_audio(self):
        """Verifies adaptation set when audio track is absent."""
        reps = [Representation("360p", 640, 360, 400, 440, 800)]
        cmd = build_ffmpeg_dash_command(
            input_path="media/input.mp4",
            manifest_name="stream.mpd",
            representations=reps,
            has_audio=False,
            segment_duration_sec=2.0,
            fps=30.0,
            ffmpeg_bin="ffmpeg",
        )
        adapt_idx = cmd.index("-adaptation_sets")
        self.assertEqual(cmd[adapt_idx + 1], "id=0,streams=v")


class TestExecutionErrorHandling(unittest.TestCase):
    """Tests error propagation when FFmpeg encounters runtime failures."""

    @patch("src.media.encode_dash.probe_video")
    @patch("subprocess.run")
    def test_encode_to_dash_ffmpeg_failure(self, mock_run, mock_probe):
        """Verifies RuntimeError on non-zero FFmpeg exit code."""
        mock_probe.return_value = VideoMetadata(
            width=1920,
            height=1080,
            duration_sec=30.0,
            fps=60.0,
            video_codec="h264",
            has_audio=True,
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "Encoder initialization failed: out of memory"
        mock_run.return_value = mock_proc

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError) as ctx:
                encode_to_dash(
                    input_path="media/input.mp4",
                    output_dir=td,
                    ffmpeg_bin="mock_ffmpeg",
                    ffprobe_bin="mock_ffprobe",
                )
            self.assertIn("FFmpeg DASH encoding failed with exit code 1", str(ctx.exception))


class TestManifestAndArtifactVerification(unittest.TestCase):
    """Tests manifest parsing and segment artifact validation on disk."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="dash_verify_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_verify_missing_manifest_raises(self):
        """Verifies FileNotFoundError if stream.mpd is not present."""
        with self.assertRaises(FileNotFoundError):
            verify_dash_output(self.test_dir, "stream.mpd")

    def test_verify_valid_manifest_and_segments(self):
        """Verifies correct parsing and validation when MPD and all segments exist."""
        mpd_content = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period id="0">
    <AdaptationSet id="0" contentType="video">
      <Representation id="0" mimeType="video/mp4" width="640" height="360" bandwidth="400000" />
      <Representation id="1" mimeType="video/mp4" width="1280" height="720" bandwidth="1500000" />
    </AdaptationSet>
  </Period>
</MPD>"""
        mpd_path = Path(self.test_dir) / "stream.mpd"
        mpd_path.write_text(mpd_content, encoding="utf-8")

        # Create dummy init and chunk segments
        (Path(self.test_dir) / "init-stream0.m4s").write_bytes(b"\x00" * 100)
        (Path(self.test_dir) / "init-stream1.m4s").write_bytes(b"\x00" * 100)
        (Path(self.test_dir) / "chunk-stream0-00001.m4s").write_bytes(b"\x00" * 500)
        (Path(self.test_dir) / "chunk-stream1-00001.m4s").write_bytes(b"\x00" * 500)

        res = verify_dash_output(self.test_dir, "stream.mpd")
        self.assertTrue(res["valid"])
        self.assertEqual(res["representations_count"], 2)
        self.assertEqual(res["init_segments_count"], 2)
        self.assertEqual(res["media_segments_count"], 2)

    def test_verify_missing_init_segment_raises(self):
        """Verifies FileNotFoundError when a representation's init segment is missing."""
        mpd_content = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period id="0">
    <AdaptationSet id="0" contentType="video">
      <Representation id="0" mimeType="video/mp4" width="640" height="360" bandwidth="400000" />
      <Representation id="1" mimeType="video/mp4" width="1280" height="720" bandwidth="1500000" />
    </AdaptationSet>
  </Period>
</MPD>"""
        mpd_path = Path(self.test_dir) / "stream.mpd"
        mpd_path.write_text(mpd_content, encoding="utf-8")

        # Create init-stream0 but NOT init-stream1
        (Path(self.test_dir) / "init-stream0.m4s").write_bytes(b"\x00" * 100)
        (Path(self.test_dir) / "chunk-stream0-00001.m4s").write_bytes(b"\x00" * 500)

        with self.assertRaises(FileNotFoundError) as ctx:
            verify_dash_output(self.test_dir, "stream.mpd")
        self.assertIn("Missing initialization segment", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
