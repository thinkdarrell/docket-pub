"""Seed additional municipalities — Vestavia Hills, Mobile, Homewood."""

SQL_UP = """
INSERT INTO municipalities (slug, name, state, county, adapter_class, adapter_config, council_type)
VALUES
    ('vestavia_hills', 'Vestavia Hills', 'AL', 'Jefferson', 'CivicClerkAdapter',
     '{"tenant": "vestaviahillsal", "category_id": 26, "delay": 0.5}', 'at_large'),
    ('mobile', 'Mobile', 'AL', 'Mobile', 'CivicClerkAdapter',
     '{"tenant": "mobileal", "category_id": 26, "delay": 0.5}', 'district'),
    ('homewood', 'Homewood', 'AL', 'Jefferson', 'GenericCMSAdapter',
     '{"archive_url": "https://www.cityofhomewood.com/city-council-archives", "video_channel": "https://www.youtube.com/channel/UCs1Om1kenQn_92rrZHj8SZQ", "delay": 1.0}', 'district');
"""

SQL_DOWN = """
DELETE FROM municipalities WHERE slug IN ('vestavia_hills', 'mobile', 'homewood');
"""
