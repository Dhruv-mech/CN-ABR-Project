"""Media encoding package for MPEG-DASH video streaming."""


def __getattr__(name: str):
    import importlib
    mod = importlib.import_module(".encode_dash", package=__name__)
    if hasattr(mod, name):
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "VideoMetadata",
    "Representation",
    "probe_video",
    "select_representation_ladder",
    "build_ffmpeg_dash_command",
    "encode_to_dash",
    "verify_dash_output",
    "find_executable",
]
