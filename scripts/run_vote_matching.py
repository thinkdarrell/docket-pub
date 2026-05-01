"""Run vote-to-agenda-item matching on all unmatched votes."""

import logging
from docket.analysis.vote_matcher import match_all_unmatched

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    result = match_all_unmatched()
    print(f"\nMatched across {result['meetings']} meetings:")
    print(f"  Timestamp matches: {result['timestamp_matched']}")
    print(f"  Text matches: {result['text_matched']}")
