"""Content source scrapers for the reading pipeline."""

from sources.bbc import BBCSource
from sources.voa import VOASource
from sources.newsinlevels import NewsInLevelsSource

ALL_SOURCES = {
    "bbc": BBCSource,
    "voa": VOASource,
    "newsinlevels": NewsInLevelsSource,
}

__all__ = ["ALL_SOURCES", "BBCSource", "VOASource", "NewsInLevelsSource"]
