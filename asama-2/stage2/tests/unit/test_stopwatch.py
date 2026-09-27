"""Stopwatch test kit: the manual analyst must work on the same data package as the system."""

import importlib.util
from pathlib import Path

from sentinel.config import load_settings


def test_manual_kit_points_at_the_configured_data_package():
    path = Path(__file__).resolve().parents[2] / "scripts" / "stopwatch.py"
    spec = importlib.util.spec_from_file_location("stopwatch", path)
    sw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sw)
    kit = sw.MANUAL_KIT.format(img="img_005672", data=sw._data_dir())
    assert str(load_settings().data_path.resolve()) in kit and "stage2_dev_data" not in kit
