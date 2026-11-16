---
title: Telephony provider data requirements
description: What the telephony provider must supply for the Mahavistar voice-services SLA.
---

The Mahavistar voice-services SLA puts hosting, speech to text, text to speech, the language model, and orchestration on the adopter. The telephony provider commits only to sections 4.8, 5.3, and 6.3. Those sections cover the phone network and the WebSocket audio connection up to the moment call audio reaches the orchestration layer.

The HTTP shapes VoicEra calls are in [Telephony SLA HTTP endpoints](telephony-sla-endpoints).

The connection is WebSocket, not SIP. Values in square brackets are agreed before signing and checked against the provider's current contract. All times are IST.

The adopter still measures one of these rows itself. Connection time in 5.3 is taken at the orchestration layer, from the call-answered time on the provider CDR to the first audio frame. That row cannot be filled without the CDR timestamp and a Call ID that matches the orchestration Call ID.

## 4.8 Phase 1: availability, redundancy, and records

| Item | Committed value | What the provider supplies |
| --- | --- | --- |
| Service availability (WebSocket connection, number, gateway) | 99.9% | The provider's own monitoring of when the WebSocket connection, number, or gateway was Down, plus enough detail to compare with the adopter's call attempts. Same formula as SLA 4.2. |
| Peak-hours availability | 99.95% | The same availability series, restricted to the peak hours fixed before signing. |
| Unplanned downtime | ≤ 43.2 min per 30-day month (other month lengths are in SLA section 3) | Start and end of every interval when the WebSocket connection, number, or gateway was Down. Approved maintenance is excluded. |
| Redundancy | At least 2 WebSocket endpoints or points of presence in separate zones. Failover, with the connection re-established, within [60 s] | Endpoint or point-of-presence record, and a connection failover test before go-live and after any change. |
| Call detail records | Delivered within [24 hours] of each day's end. Each CDR carries the Call ID that matches the orchestration Call ID | Daily CDRs, including calls that never connected, and a sample match against orchestration logs. |

Incident handling on the provider side:

| Priority | When it applies | Notify | Update | Restore | RCA |
| --- | --- | --- | --- | --- | --- |
| P0 | WebSocket connection, number, or gateway is Down, or calls are failing at scale | 5 min | Every 15 min | 2 hours | Preliminary in 24 hours, final in 5 working days |
| P1 | Connection is up, and more than 10% of calls are hit by setup failures, carrier-side drops, or poor audio | 10 min | Every 30 min | 4 hours | Preliminary in 48 hours, final in 7 working days |
| P2 | 10% of calls or fewer are hit by the same | 30 min | Every 2 hours | 1 working day | Final only, in 5 working days, if repeated or customer-impacting |

P0 and P1 are covered 24 × 7. P2 is covered Monday to Friday, 09:00 to 18:00 IST. The provider's operations lead is added to the escalation path in SLA 4.6 while a telephony incident is open. Names and numbers go in Appendix C.

Planned maintenance needs at least 7 days' notice, outside peak hours, inside an agreed window.

Monthly report, by the 5th working day of the next month: Actual values for the tables in 4.8, 5.3, and 6.3, plus incidents and open actions.

## 5.3 Phase 2: speed, quality, and errors

Latency and error limits are checked on rolling 5-minute windows. More than 10% of calls affected is P1. 10% or fewer is P2. Priorities are the ones in 4.8. Before go-live, each row is measured in a production-like setup and must already meet the committed value.

| Metric | Committed value | What the provider supplies |
| --- | --- | --- |
| Call setup success rate | [99%] | Connected calls and valid call attempts, with failure codes. |
| Post-dial delay (dial to ring or answer signal) | p95 ≤ [3 s] | CDR timestamps for dial start and for ring or answer signal. |
| Connection time (call answered to WebSocket open and first audio received by orchestration) | p95 ≤ [500 ms] | Call-answered time on the CDR, joined to the orchestration Call ID. The adopter measures the first audio frame. |
| One-way media latency in the provider's network | ≤ [150 ms] | Per-call or aggregated statistics on the WebSocket audio stream. |
| Jitter | ≤ [30 ms] | The same, measured on the WebSocket audio stream. |
| Packet loss | ≤ [1%] | The same, measured on the WebSocket audio stream. |
| Audio quality (MOS) | ≥ [3.8] | MOS, or the measurements MOS is computed from, in a quality report. |
| Carrier-side call drops | ≤ [0.5%] | Calls dropped by the carrier, or dropped before call audio reaches the orchestration layer, with the reason. These are excluded from the adopter's unexpected-drop row in 5.2 so a call is not counted twice. |
| Number and call routing | 100% of calls reach the assigned number and flow | A CDR audit of number and flow. |

## 6.3 Phase 3: load and capacity

Every target in 4.8 and 5.3 still applies at full committed capacity. The load test in SLA 6.1 runs through the provider's WebSocket connections.

| Metric | Committed value | What the provider supplies |
| --- | --- | --- |
| Connection capacity | At least 875 concurrent WebSocket connections (700 × 1.25) reserved at all times, plus [10 to 20%] burst headroom | A capacity record, and participation in the load test. |
| Calls rejected below the limit | 0% | Rejected calls and call attempts while connections in use are under 875. Rejection under 875 is a P1 incident. |
| Behaviour above the limit | 100% get a clear busy or capacity signal, with no silent failure | Over-limit calls and whether each returned a clear signal. A clear signal above 875 is not an incident and is not counted against the SLA. |
| Speed and quality at full load | The 5.3 targets still met at 875 concurrent calls | The 5.3 measurements taken at that load, marked Pass or Fail. |
| Early capacity warning | Alerts to the adopter at 80% (700) and 90% (788) of 875 connections | Alert events, and any time usage crossed 80% or 90% with no alert. Target is zero misses. |
| Scale-up time | Up to [+X] connections above 875 ready within [30 min] of the warning | Time from the warning to the extra connections carrying calls. |
| Soak test | 875 concurrent connections held for 4 hours, with all 5.3 targets met and no failure | Pass or Fail in the load test report. |

## Fields each CDR needs

- Call ID, the same identifier as the orchestration Call ID
- Direction, from number, and to number
- Assigned number and the flow the call was routed to
- Dial start time
- Ring or answer-signal time
- Call-answered time
- Disconnect time
- Setup result and failure code
- Disconnect reason, including whether the drop was on the carrier side or before audio reached orchestration
- One-way media latency, jitter, packet loss, and MOS when the call had media

Clocks are IST and stay in sync with the orchestration layer.

## Already in VoicEra, and still not enough

Answer and hangup webhooks already carry from, to, direction, a provider call ID, call status, and hangup cause. Hangup cause is kept only when it maps to busy, no answer, failed, or cancelled. The VI pull-call-details report already has call ID, dial status, dial start, duration, recording URL, circle, and operator.

That does not cover WebSocket, number, and gateway uptime, a second WebSocket endpoint with a timed failover, CDRs joined on the orchestration Call ID, post-dial and answered timestamps, WebSocket media statistics, MOS, a reserved 875-connection record, rejection and busy-signal counts, 80% and 90% alerts, or the monthly Actuals for 4.8, 5.3, and 6.3.
