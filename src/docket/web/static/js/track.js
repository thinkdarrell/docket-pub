/* docket.pub event tracker.
 *
 * Single source of truth for custom analytics events. Two responsibilities:
 *
 *   1. Wrap window.umami.track() with try/catch so a blocked or absent
 *      analytics script can NEVER break a click handler or other UX.
 *   2. Enforce the PII guardrail: drop any string-valued property longer
 *      than QUERY_MAX_LEN before sending. Most legitimate topic searches
 *      ("flock cameras", "zoning board") are short; addresses and PII
 *      run long. Drop rather than truncate — truncating still leaks the
 *      address prefix ("1234 Maple S…" identifies the house).
 *
 * Usage:
 *   docketTrack('outbound_source_click', {
 *     source_type: 'granicus_video',
 *     target_domain: 'bhamal.granicus.com',
 *     item_id: 12345,
 *   });
 */
(function () {
  'use strict';

  var QUERY_MAX_LEN = 40;

  function sanitizeProps(props) {
    var out = {};
    if (!props) return out;
    var keys = Object.keys(props);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      var v = props[k];
      if (typeof v === 'string' && v.length > QUERY_MAX_LEN) continue;
      out[k] = v;
    }
    return out;
  }

  window.docketTrack = function (name, props) {
    try {
      if (window.umami && typeof window.umami.track === 'function') {
        window.umami.track(name, sanitizeProps(props));
      }
    } catch (e) {
      // Analytics blocked or failed — never break the page.
    }
  };

  // Exposed for unit-style verification in the browser console:
  //   window.__docketTrackInternals.sanitizeProps({q: 'x'.repeat(50)}) // → {}
  window.__docketTrackInternals = { sanitizeProps: sanitizeProps, QUERY_MAX_LEN: QUERY_MAX_LEN };
})();
