# Mouth Size / Coverage Grid

Coverage-normalized survey for checking whether the mouth-size / horn-length
heuristic changes across target coverage angles.

Fixed variables per search:

- K: 4 on both axes
- N: 10 on both axes
- sweep: 500-8000 Hz
- crossover: 750 Hz
- conical extension: 0 mm
- round mouths only; horizontal and vertical dimensions match

Each search folder fixes one coverage target and one mouth size, then compares
five length candidates spaced by mouth/length ratio. The wider coverage cases
need shorter horns at K=4 to keep the OS-SE solved `s` nonnegative:

- 35 deg and 45 deg ratios: 2.2, 2.4, 2.6, 2.8, 3.0
- 60 deg ratios: 3.3, 3.5, 3.7, 4.0, 4.3
- 75 deg ratios: 7.2, 7.6, 8.0, 8.5, 9.0
- seed ratio: the middle ratio in each coverage set

The experiment grid is:

- coverage targets: 35, 45, 60, 75 deg
- mouth sizes: 300, 350, 400, 450, 500 mm
- search folders: one per coverage/mouth pair

Each search evaluates the seed candidate plus four initial-pool candidates, with
the seed placed at the middle ratio. The layout is intended to expose whether a
useful mouth/length ratio band shifts with coverage.
