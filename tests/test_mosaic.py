import cv2
import numpy as np
import pytest

from deface.deface import draw_det


@pytest.mark.parametrize('channels', [3, 4])
@pytest.mark.parametrize('mosaic_size', [2, 3, 20])
def test_mosaic_preserves_alpha_and_rgb_behavior(channels, mosaic_size):
    frame = np.random.default_rng(0).integers(0, 256, (12, 14, channels), dtype=np.uint8)
    original = frame.copy()
    expected_rgb = frame[:, :, :3].copy()
    x1, y1, x2, y2 = 2, 3, 11, 10

    # Match the existing RGB mosaic, including partial blocks at the edges.
    for y in range(y1, y2, mosaic_size):
        for x in range(x1, x2, mosaic_size):
            color = tuple(int(value) for value in expected_rgb[y, x])
            cv2.rectangle(
                expected_rgb, (x, y),
                (min(x2, x + mosaic_size - 1), min(y2, y + mosaic_size - 1)),
                color, -1,
            )

    draw_det(frame, 1.0, 0, x1, y1, x2, y2, replacewith='mosaic', mosaicsize=mosaic_size)

    np.testing.assert_array_equal(frame[:, :, :3], expected_rgb)
    assert np.any(frame[:, :, :3] != original[:, :, :3])
    if channels == 4:
        np.testing.assert_array_equal(frame[:, :, 3], original[:, :, 3])
