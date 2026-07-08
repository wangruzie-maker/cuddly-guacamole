"""Discover plugins — import side-effects register sources."""

from discover.channels_account_recent import ChannelsAccountRecentSource
from discover.channels_search_keyword import ChannelsSearchKeywordSource
from discover.channels_topic_hot import ChannelsTopicHotSource
from discover.xhs_account_notes import XhsAccountNotesSource
from discover.xhs_search_keyword import XhsSearchKeywordSource
from core.discover_registry import register

register(ChannelsTopicHotSource())
register(ChannelsSearchKeywordSource())
register(ChannelsAccountRecentSource())
register(XhsSearchKeywordSource())
register(XhsAccountNotesSource())
