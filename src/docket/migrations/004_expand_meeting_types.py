"""Expand adapters to scrape all meeting types, not just city council.

Vestavia Hills: Remove category_id filter to scrape all 8 event categories.
Homewood: Add archive URLs for committees, boards, and commissions.
"""

SQL_UP = """
-- Vestavia Hills: scrape all categories (remove category_id filter)
UPDATE municipalities
SET adapter_config = '{"tenant": "vestaviahillsal", "delay": 0.5}'
WHERE slug = 'vestavia_hills';

-- Homewood: add all archive pages
UPDATE municipalities
SET adapter_config = '{"archive_urls": ["https://www.cityofhomewood.com/city-council-archives", "https://www.cityofhomewood.com/precouncil-archives", "https://www.cityofhomewood.com/bza-archives", "https://www.cityofhomewood.com/planning-commission-archives", "https://www.cityofhomewood.com/finance-committee-archives", "https://www.cityofhomewood.com/public-safety-committee-archives", "https://www.cityofhomewood.com/public-works-committee-archives", "https://www.cityofhomewood.com/planning---development-committee-archives", "https://www.cityofhomewood.com/special-issues-committee-archives", "https://www.cityofhomewood.com/library-board-archives", "https://www.cityofhomewood.com/historic-preservation-commission-archives"], "video_channel": "https://www.youtube.com/channel/UCs1Om1kenQn_92rrZHj8SZQ", "delay": 1.0}'
WHERE slug = 'homewood';
"""

SQL_DOWN = """
-- Restore original configs
UPDATE municipalities
SET adapter_config = '{"tenant": "vestaviahillsal", "category_id": 26, "delay": 0.5}'
WHERE slug = 'vestavia_hills';

UPDATE municipalities
SET adapter_config = '{"archive_url": "https://www.cityofhomewood.com/city-council-archives", "video_channel": "https://www.youtube.com/channel/UCs1Om1kenQn_92rrZHj8SZQ", "delay": 1.0}'
WHERE slug = 'homewood';
"""
