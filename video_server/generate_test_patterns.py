"""Generate 20 MP4 test pattern files for WINTS video server.

Creates colour-bar test patterns using OpenCV for all 10 targets
× 2 cameras (front/rear). Each is a 640x360, 25fps, 30-second video.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "video_server" / "samples"


def _make_frame(target_id: str, cam: str, frame_num: int, total_frames: int) -> np.ndarray[np.uint8, np.dtype[np.uint8]]:
    """Create a single annotated test pattern frame."""
    # Dark navy background
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[:] = (29, 32, 53)  # BGR: #35201d reversed → dark navy

    # Colour bars at the bottom (classic TV test pattern strip)
    bar_colors = [
        (192, 192, 192),  # white
        (192, 192, 0),    # yellow
        (0, 192, 192),    # cyan
        (0, 192, 0),      # green
        (192, 0, 192),    # magenta
        (192, 0, 0),      # red
        (0, 0, 192),      # blue
    ]
    bar_w = 640 // len(bar_colors)
    for i, color in enumerate(bar_colors):
        x1, x2 = i * bar_w, (i + 1) * bar_w
        frame[300:340, x1:x2] = color

    # Target ID — large white text
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_main = f"{target_id}"
    text_size, _ = cv2.getTextSize(text_main, font, 2.0, 3)
    x_main = (640 - text_size[0]) // 2
    cv2.putText(frame, text_main, (x_main, 160), font, 2.0, (220, 214, 244), 3, cv2.LINE_AA)

    # Camera label
    cam_color = (49, 205, 166) if cam == "FRONT" else (88, 166, 255)  # green / blue
    cv2.putText(frame, f"CAM: {cam}", (20, 30), font, 0.55, cam_color, 1, cv2.LINE_AA)

    # WINTS header
    cv2.putText(frame, "WINTS LIVE FEED", (20, 55), font, 0.45, (137, 180, 250), 1, cv2.LINE_AA)

    # Simulated timestamp counter
    secs = frame_num // 25
    frames = frame_num % 25
    ts = f"SIM {secs // 60:02d}:{secs % 60:02d}.{frames:02d}"
    cv2.putText(frame, ts, (480, 30), font, 0.45, (108, 112, 134), 1, cv2.LINE_AA)

    # Status: ONLINE
    status_text = "STATUS: ONLINE"
    cv2.putText(frame, status_text, (20, 355), font, 0.4, (166, 227, 161), 1, cv2.LINE_AA)

    # Blinking dot (every 25 frames)
    if (frame_num // 12) % 2 == 0:
        cv2.circle(frame, (610, 25), 8, (166, 227, 161), -1)

    return frame  # type: ignore[return-value]


def generate_all() -> None:
    """Generate 20 MP4 test pattern videos."""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    fps = 25
    duration_s = 30
    total_frames = fps * duration_s
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]

    for i in range(1, 11):
        target_id = f"T-{i:02d}"
        for cam in ["FRONT", "REAR"]:
            filename = f"target-{i:02d}-{cam.lower()}.mp4"
            out_path = SAMPLES_DIR / filename
            print(f"  Generating {filename}...", end="", flush=True)

            writer = cv2.VideoWriter(str(out_path), fourcc, fps, (640, 360))
            for f in range(total_frames):
                frame = _make_frame(target_id, cam, f, total_frames)
                writer.write(frame)
            writer.release()
            print(f" DONE ({out_path.stat().st_size // 1024} KB)")

    print(f"\nAll 20 test pattern videos written to: {SAMPLES_DIR}")


if __name__ == "__main__":
    print("Generating WINTS test pattern videos...")
    generate_all()
    print("Complete.")
