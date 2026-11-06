# 0081 — The two ends of a recording's coverage are checked in 60-second pieces, and the coverage runs from the first piece that confirms to the last

## Decision

Coverage is the span from the first confirmed window to the last with each end moved inward to the first piece of `EDGE_S` seconds (60) that confirms the offset by the test a window gets (`confirmed_span` in `transcriber/transcriber/align.py`); a recording that meets the pass mark and has no confirming piece is rejected with reason `edges`. The pieces move the coverage only: the offset, the score, the window counts, and the pass mark are the windows', as decision `0078` left them. This is method version 2.

## Rationale

Decision `0078` made coverage the span of the confirmed windows "because outside it nothing has checked that the recordings still run together". The same was true inside the first and last windows: a five-minute window confirms when most of it matches, so other audio in its outer part stayed covered and a link there opened YouTube at the wrong second. The closing review found this on synthetic audio (`D107` at the start, `D96` at the end, each recorded as about 150 to 160 seconds). On 2026-11-06 it was reproduced on the labelled real recordings the pass mark was chosen from, and it was larger: with another meeting's audio over the first 200 seconds of the recording of clip 2026, and over the first 250 seconds of the recording of clip 1530, the recording passed with coverage from its first second. The same audio showed a real case nobody had labelled: both uploads of clip 1831 begin with about 330 seconds of silence, and their first window had confirmed by accident.

Leaving it as a known limit was the alternative, and the limit had been accepted on the grounds that no real pair showed a cut. It was closed now because nothing had been measured in production: a change of method is free until the first measuring run and costs a second download of every attached recording after it.

A finer check cannot be made certain on this audio. On the five labelled pairs from 2026 a 60-second piece of a true match confirms only about a third of the time (19 of 57 on clip 2026, 24 of 90 on clip 2004), against nearly always on the three older pairs, so a rule that waited for certainty would cover almost nothing of a current recording. The rule therefore takes the first piece that confirms and accepts two limits. The piece that holds the boundary can confirm on its matching part, so less than one piece of other audio can stay covered. And a piece of other audio confirms by accident about one time in twenty (the 4 seconds of `AGREE_S` against the 80 of `LOCAL_SEARCH_S`): of 30 splices of another meeting's audio over the first or last 60 to 250 seconds of four real recordings, the windows alone kept every spliced second covered in 21; with the pieces, one kept more than a piece covered (190 of 250 seconds at the end of clip 2026's recording) and the other 29 kept 40 seconds or less. Pieces of 30 seconds were tried: they gave up about as much coverage on the pairs without silence, and a silent piece of clip 1831 confirmed by accident; pieces of 150 seconds leave up to 150 seconds covered, which is the fault itself.

The price is coverage, and links in what is given up open Granicus. On the nine labelled pairs the coverage starts 0 to 240 seconds later than the windows' span and ends 0 to 240 seconds earlier (360 seconds later on the two uploads of clip 1831, the silent stretch); the two strong pairs with no silence, clips 1530 and 942, lose nothing. All nine still pass and all 63 mismatched pairings are still rejected on score, with the same offsets, scores, and window counts as in the table decision `0078` cites, because the pieces do not enter the pass mark.

## Date

2026-11-06, the operator, choosing both ends over the start alone and over leaving `D107` open, from Claude's measurements on the labelled recordings in the session that followed the closing review of plan `video-links-land-on-the-moment`.

## Status

accepted
