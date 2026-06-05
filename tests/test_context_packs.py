"""Tests for context_packs path validation (Wave 2.1)."""

import pytest

from promptgenie.core.context_packs import _validate_pack_id


class TestPackIdValidation:
    def test_valid_ids_accepted(self):
        for valid in ("react-app", "my_pack", "Pack1", "a", "A-b_C-1"):
            _validate_pack_id(valid)  # must not raise

    def test_dotdot_traversal_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("../etc/passwd")

    def test_dotdot_simple_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("..")

    def test_dot_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id(".")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("")

    def test_slash_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("foo/bar")

    def test_absolute_path_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("/etc/passwd")

    def test_space_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("my pack")

    def test_unicode_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("café")

    def test_null_byte_rejected(self):
        with pytest.raises(ValueError, match="Invalid pack ID"):
            _validate_pack_id("foo\x00bar")
