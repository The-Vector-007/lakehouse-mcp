"""Allowlisted roots. The other half of the guarantee."""

import pytest

from lakehouse_mcp.config import HARD_MAX_ROWS, AccessDenied, Config


def test_allows_paths_inside_a_root(config, lakehouse):
    assert config.resolve(str(lakehouse / "silver")).name == "silver"


def test_allows_the_root_itself(config, lakehouse):
    assert config.resolve(str(lakehouse)) == lakehouse.resolve()


def test_refuses_paths_outside_every_root(config):
    with pytest.raises(AccessDenied):
        config.resolve("/etc")


def test_refuses_traversal_out_of_a_root(config, lakehouse):
    """Resolve before checking, or '..' walks straight out."""
    with pytest.raises(AccessDenied):
        config.resolve(str(lakehouse / "silver" / ".." / ".." / ".." / "etc"))


def test_refuses_a_symlink_pointing_out(config, lakehouse, tmp_path):
    """The check follows symlinks, so a contained-looking path cannot escape."""
    secret = tmp_path / "outside"
    secret.mkdir()
    link = lakehouse / "escape"
    link.symlink_to(secret)

    with pytest.raises(AccessDenied):
        config.resolve(str(link))


def test_refuses_everything_when_no_roots_are_configured():
    with pytest.raises(AccessDenied):
        Config().resolve("/anything")


def test_row_limit_is_clamped_however_much_is_asked_for(config):
    assert config.clamp_rows(None) == config.max_rows
    assert config.clamp_rows(5) == 5
    assert config.clamp_rows(10**9) == HARD_MAX_ROWS
    assert config.clamp_rows(0) == 1
    assert config.clamp_rows(-5) == 1
