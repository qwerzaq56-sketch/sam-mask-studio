import json

from src.app.settings import ROOT, Settings


def test_checkpoint_paths_inside_the_app_are_stored_relative(tmp_path):
    cfg = tmp_path / "config.json"
    s = Settings()
    s.sam3_checkpoint = str(tmp_path / "elsewhere.pt")  # outside the app folder: stays absolute
    s.save(cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["sam2_checkpoint"] == "checkpoints/sam2/sam2.1_hiera_tiny.pt"
    assert data["sam3_checkpoint"] == str(tmp_path / "elsewhere.pt")
    again = Settings.load(cfg)
    assert again.sam2_checkpoint == str(ROOT / "checkpoints/sam2/sam2.1_hiera_tiny.pt")
    assert again.sam3_checkpoint == str(tmp_path / "elsewhere.pt")
