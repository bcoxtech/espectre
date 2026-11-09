"""
Micro-ESPectre - CSI Data Collection Tests

Tests for tools/csi_utils.py's CSICollector.save_sample(): the (x, y, node_id)
calibration-walk tagging added for CLA-273, plus the pre-existing untagged
path it must not regress. Disk I/O (DATA_DIR / dataset_info.json) is isolated
per test via monkeypatch so these never touch the real dataset.

Author: Claude <noreply@anthropic.com>
License: GPLv3
"""

import json
import math

import numpy as np
import pytest

from csi_utils import CSICollector, CSIPacket


def make_packet(seq_num=0, chip="S3", gain_locked=True, num_subcarriers=64):
    """Build a minimal CSIPacket sufficient for save_sample()."""
    iq_raw = np.zeros(num_subcarriers * 2, dtype=np.int8)
    return CSIPacket(
        timestamp=1000.0 + seq_num * 0.01,
        seq_num=seq_num,
        num_subcarriers=num_subcarriers,
        iq_raw=iq_raw,
        iq_complex=np.zeros(num_subcarriers, dtype=np.complex64),
        amplitudes=np.zeros(num_subcarriers, dtype=np.float32),
        phases=np.zeros(num_subcarriers, dtype=np.float32),
        chip=chip,
        gain_locked=gain_locked,
    )


@pytest.fixture
def isolated_data_dir(monkeypatch, tmp_path):
    """Redirect csi_utils' DATA_DIR/DATASET_INFO_FILE at a throwaway directory."""
    import csi_utils

    data_dir = tmp_path / "data"
    monkeypatch.setattr(csi_utils, "DATA_DIR", data_dir)
    monkeypatch.setattr(csi_utils, "DATASET_INFO_FILE", data_dir / "dataset_info.json")
    return data_dir


# allow_pickle=True is required because npz stores the str/object fields
# (label, chip, node_id) as 0-d object arrays; every file loaded here was
# just written by this same test process, matching the repo's existing
# load_npz_as_packets() convention, not an untrusted external source.


def load_dataset_info(data_dir):
    with open(data_dir / "dataset_info.json", "r") as f:
        return json.load(f)


class TestSaveSampleUntagged:
    """Pre-existing behavior: collect without --x/--y/--node-id."""

    def test_saved_npz_has_nan_position_and_empty_node_id(self, isolated_data_dir):
        collector = CSICollector(label="baseline", contributor="tester")
        filepath = collector.save_sample([make_packet(0), make_packet(1)])

        data = np.load(filepath, allow_pickle=True)
        assert math.isnan(float(data["x"]))
        assert math.isnan(float(data["y"]))
        assert str(data["node_id"]) == ""

    def test_dataset_info_omits_position_fields(self, isolated_data_dir):
        collector = CSICollector(label="baseline", contributor="tester")
        collector.save_sample([make_packet(0), make_packet(1)])

        info = load_dataset_info(isolated_data_dir)
        file_info = info["files"]["baseline"][0]
        assert "x" not in file_info
        assert "y" not in file_info
        assert "node_id" not in file_info


class TestSaveSampleTagged:
    """New behavior: calibration-walk tagging via x/y/node_id."""

    def test_saved_npz_stores_position_and_node_id(self, isolated_data_dir):
        collector = CSICollector(label="calib", contributor="tester", x=1.5, y=2.0, node_id="node1")
        filepath = collector.save_sample([make_packet(0), make_packet(1)])

        data = np.load(filepath, allow_pickle=True)
        assert float(data["x"]) == 1.5
        assert float(data["y"]) == 2.0
        assert str(data["node_id"]) == "node1"

    def test_dataset_info_includes_position_fields(self, isolated_data_dir):
        collector = CSICollector(label="calib", contributor="tester", x=1.5, y=2.0, node_id="node1")
        collector.save_sample([make_packet(0), make_packet(1)])

        info = load_dataset_info(isolated_data_dir)
        file_info = info["files"]["calib"][0]
        assert file_info["x"] == 1.5
        assert file_info["y"] == 2.0
        assert file_info["node_id"] == "node1"

    def test_zero_coordinates_are_not_treated_as_untagged(self, isolated_data_dir):
        """x=0.0, y=0.0 is a valid grid origin, not 'no position given'."""
        collector = CSICollector(label="calib", contributor="tester", x=0.0, y=0.0, node_id="node1")
        filepath = collector.save_sample([make_packet(0), make_packet(1)])

        data = np.load(filepath, allow_pickle=True)
        assert float(data["x"]) == 0.0
        assert float(data["y"]) == 0.0

        info = load_dataset_info(isolated_data_dir)
        file_info = info["files"]["calib"][0]
        assert file_info["x"] == 0.0
        assert file_info["y"] == 0.0
