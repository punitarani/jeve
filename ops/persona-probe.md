# Persona sensitivity probe

Run 2026-09-20 18:27 UTC against `typesafe/jev-1.13`. 280 live calls, $0.004631, cache bypassed. 20 samples per persona per case.

**Question:** with the situation held fixed and only the person's temperament changed from its lowest tertile to its highest, does Jev return a different distribution — by more than its own noise?

**Answer: 6 of 6 test cases are clearly distinct, and the control held.** Sampling Jev's distributions preserves persona where persona is relevant, and leaves it alone where it is not.

| question set | situation (held fixed) | P(yes) low trait | P(yes) high trait | between (bits) | noise (bits) | ratio | verdict |
|---|---|---|---|---|---|---|---|
| `cafe.purchase` | several people are ahead of them and the line is slow; The cafe is running normally and taking cards. | 0.389 ± 0.008 | 0.838 ± 0.006 | 0.1605 | 0.000052 | 3,092× | **distinct** |
| `cafe.purchase` | several people are ahead of them and the line is slow; The card reader is broken; the cafe is taking cash only and service is slow. | 0.344 ± 0.010 | 0.775 ± 0.007 | 0.1415 | 0.000060 | 2,352× | **distinct** |
| `cafe.purchase` | nobody is waiting; they can be served at once; The cafe is running normally and taking cards. | 0.828 ± 0.005 | 0.844 ± 0.006 | 0.0003 | 0.000039 | 8× | **flat, as it should be** |
| `ticket.answer` | busy; a long list of open tickets; mid-morning | 0.244 ± 0.005 | 0.778 ± 0.007 | 0.2165 | 0.000036 | 5,987× | **distinct** |
| `file.ticket` | A feature of the software that they use for work has just stopped responding. They have not reported it yet. | 0.071 ± 0.004 | 0.398 ± 0.018 | 0.1161 | 0.000152 | 762× | **distinct** |
| `payment.timing` | the invoice is a few days overdue; there is comfortably enough cash to pay it | 0.252 ± 0.010 | 0.709 ± 0.016 | 0.1567 | 0.000154 | 1,017× | **distinct** |
| `payment.timing` | the invoice is a few days overdue; cash is tight; paying this leaves little in the account | 0.244 ± 0.007 | 0.567 ± 0.019 | 0.0795 | 0.000160 | 498× | **distinct** |

Reading it. *between* is the Jensen-Shannon divergence between the two personas' mean answers; *noise* is the mean divergence of a persona's samples from its own mean, where samples differ only in a throwaway reference field. `distinct` needs a gap of at least 0.10 in P(yes) **and** at least 10× the noise; `FLAT` is a gap under 0.03.

The control row is a situation where temperament should *not* matter — a patient and an impatient customer behave alike at an empty counter. It is there so that "Jev respects persona" can be told apart from "Jev moves whenever any word changes".

What this does not show: that the *levels* are right. Jev puts a patient customer at an empty counter at about 0.84 to buy; whether a real cafe loses one walk-in in six is a calibration question this probe cannot answer. It shows the traits are load-bearing, not that the magnitudes are true.
