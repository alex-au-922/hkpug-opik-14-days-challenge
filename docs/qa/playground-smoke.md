# Tournament Playground Smoke

Date: 2026-07-12

## Result

The playground ran the same two discovery cases and one holdout case against
Fireworks DeepSeek V4 Flash. Each run made three answer calls and three judge
calls with `reasoning_effort: none`.

| Prompt | Discovery | Holdout | Overall | Run |
| --- | ---: | ---: | ---: | --- |
| Baseline | 100.0 | 100.0 | 100.0 | [29197438251](https://github.com/alex-au-922/hkpug-opik-14-days-challenge/actions/runs/29197438251) |
| Weak control | 0.0 | 0.0 | 0.0 | [29197404999](https://github.com/alex-au-922/hkpug-opik-14-days-challenge/actions/runs/29197404999) |

The downloaded artifacts were also checked directly. Discovery includes full
case inputs, model outputs, criterion contributions, reasons, and usage. The
holdout includes only aggregate criterion contributions and its score. Neither
artifact contains the participant prompt.

## Design Finding

An earlier smoke placed the participant prompt in the system role while a
later fixed user message supplied the complete answer recipe. Both the baseline
and deliberately weak prompt then scored 100, so that layout could not support
a prompt tournament. The corrected layout uses a minimal fixed safety system
message and appends the participant prompt after the context and question.

## Still Unproven

- Score distribution and stability across the real private 50-case bank.
- Judge calibration against human labels and intermediate-quality prompts.
- Eight-attempt state, encrypted feedback, Opik replay, and leaderboard flow.
