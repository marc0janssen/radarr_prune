from app import __version__
from app.__version__ import __version__ as __version__direct


def test_version_string_non_empty():
    assert isinstance(__version__, str)
    assert len(__version__) >= 3


def test_version_single_source():
    assert __version__ == __version__direct
