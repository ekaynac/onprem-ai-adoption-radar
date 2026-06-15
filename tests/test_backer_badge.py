from radar.models import Backer, BackerType
from radar.web.backer_badge import backer_badge


def test_badge_none_for_missing_backer():
    assert backer_badge(None) is None


def test_badge_big_tech():
    b = backer_badge(Backer(name="NVIDIA", type=BackerType.BIG_TECH))
    assert b is not None
    assert b.name == "NVIDIA"
    assert b.type == "big_tech"
    assert b.emoji == "🏢"
    assert b.label == "Big Tech"
    assert b.title == "NVIDIA — Big Tech"


def test_badge_covers_every_type():
    # Every BackerType must render a distinct emoji + non-empty label, so no
    # configured backer falls through to a bare placeholder.
    seen_emoji = set()
    for t in BackerType:
        b = backer_badge(Backer(name="x", type=t))
        assert b is not None
        assert b.emoji and b.label
        seen_emoji.add(b.emoji)
    assert len(seen_emoji) == len(list(BackerType))
