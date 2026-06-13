"""
Unit tests for the watch_config module.
"""

from pathlib import Path

import pytest
from utils.watch_config import ConfigValidationError, load_config


def test_load_config_missing_file(tmp_path: Path):
    with pytest.raises(ConfigValidationError, match="Configuration file not found"):
        load_config(tmp_path / "nonexistent.yaml")


def test_load_config_empty_file(tmp_path: Path):
    config_file = tmp_path / "empty.yaml"
    config_file.touch()
    with pytest.raises(ConfigValidationError, match="is empty or not a mapping"):
        load_config(config_file)


def test_load_config_missing_required_fields(tmp_path: Path):
    config_file = tmp_path / "invalid.yaml"
    config_file.write_text("target_roles: []\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="'target_roles' is required"):
        load_config(config_file)


def test_load_config_success(tmp_path: Path):
    yaml_content = """
target_roles:
  - "Software Engineer"
locations:
  - "Remote"
role_aliases:
  "Software Engineer":
    - "SWE"
preferred_companies:
  - "OpenAI"
preferences:
  minimum_match_score: 50
scrape:
  results_wanted: 10
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")
    
    config = load_config(config_file)
    
    assert config.target_roles == ["Software Engineer"]
    assert config.locations == ["Remote"]
    assert config.role_aliases == {"Software Engineer": ["SWE"]}
    assert config.preferred_companies == ["OpenAI"]
    assert config.preferences.minimum_match_score == 50
    assert config.scrape.results_wanted == 10
    
    # Check defaults
    assert config.scrape.hours_old == 24
    assert config.report.format == "markdown"
    assert config.email.enabled is False
