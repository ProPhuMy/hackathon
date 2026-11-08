from unittest.mock import patch

import numpy as np

from src.cli.record import record_command


def test_record_command(tmp_path):
    out_video = tmp_path / "rec.mp4"
    frame_mock = np.zeros((40, 40, 3), dtype=np.uint8)

    with patch(
        "src.cli.record.iter_frames",
        return_value=[
            (frame_mock, "2026-11-07T19:40:00.000Z"),
            (frame_mock, "2026-11-07T19:40:00.066Z"),
        ],
    ):
        record_command("http://dummy", str(out_video))

    assert out_video.exists()
    assert out_video.stat().st_size > 0
