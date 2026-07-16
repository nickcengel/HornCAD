# Mouth Size / Length Survey

Round-axisymmetric staged survey for learning the first-order relationship
between mouth size, length, and 45 deg coverage behavior before K/N fine tuning.

Fixed variables:

- target coverage: 45 x 45 deg
- OS-SE coverage: 45 x 45 deg
- K: 4 on both axes
- N values: 6, 10, 15, 20
- sweep: 500-8000 Hz
- crossover: 750 Hz
- conical extension: 0 mm
- round mouths only; horizontal and vertical dimensions match

Length grids are mouth-specific so every staged K=4/N candidate stays within
the nonnegative-S feasibility region and the current derived S bound [0, 5].

| Sub-search | Mouth mm | Lengths mm | Candidates |
| --- | ---: | --- | ---: |
| `300x300` | 300 | 110, 122, 134, 146, 158 | 20 |
| `350x350` | 350 | 125, 140, 155, 170, 185 | 20 |
| `400x400` | 400 | 140, 160, 180, 200, 205 | 20 |
| `450x450` | 450 | 155, 175, 195, 215, 230 | 20 |
| `500x500` | 500 | 180, 200, 220, 235, 250 | 20 |

These files are staged only. Launch a sub-search explicitly when ready, for example:

```bash
python app/tools/run_bem_search.py examples/mouth-size-length-survey/400x400/search.yaml --output-dir examples/mouth-size-length-survey/400x400
```
