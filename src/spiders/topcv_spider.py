from src.core.settings import settings
from src.spiders.base_spider import BaseSpider


class TopcvSpider(BaseSpider):
    source = "topcv"

    def list_url(self) -> str:
        return settings.topcv_list_url

    def _delay_range(self) -> tuple[float, float]:
        return (settings.delay_topcv_min, settings.delay_topcv_max)
