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

  /* Classify an outbound URL into a source_type.
   * Returns null when the URL is internal (same host) or unparseable.
   * The five classifications match the spec's v1 outbound_source_click `source_type`.
   */
  function classifyOutbound(url) {
    var u;
    try {
      u = new URL(url, window.location.href);
    } catch (e) {
      return null;
    }
    if (u.hostname === window.location.hostname) return null;
    var host = u.hostname.toLowerCase();
    var path = u.pathname.toLowerCase();

    if (host.indexOf('granicus.com') !== -1) return 'granicus_video';
    if (path.endsWith('.pdf')) {
      if (path.indexOf('minute') !== -1) return 'minutes_pdf';
      return 'agenda_pdf';  // PDFs on city sites default to agenda_pdf
    }
    // Known Alabama city/government hostnames map to city_site.
    var cityHosts = [
      'birminghamal.gov', 'cityofvestavia.com', 'cityofhomewood.com',
      'mobile.org', 'cityofmobile.org', 'hooveralabama.gov',
      'montgomeryal.gov',
    ];
    for (var i = 0; i < cityHosts.length; i++) {
      if (host === cityHosts[i] || host.endsWith('.' + cityHosts[i])) return 'city_site';
    }
    return 'other';
  }

  // Exposed for unit-style verification in the browser console:
  //   window.__docketTrackInternals.sanitizeProps({q: 'x'.repeat(50)}) // → {}
  //   window.__docketTrackInternals.classifyOutbound('https://bhamal.granicus.com/…') // → 'granicus_video'
  window.__docketTrackInternals = {
    sanitizeProps: sanitizeProps,
    QUERY_MAX_LEN: QUERY_MAX_LEN,
    classifyOutbound: classifyOutbound,
  };
})();
