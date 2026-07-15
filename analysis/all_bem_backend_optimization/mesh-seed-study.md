# Authored STL tessellation study

This meshing-only study selects the HornCAD STL tessellation supplied to the
Netgen wavelength remesher. It does not change the final acoustic requirement
of six elements per wavelength and performs no BEM solves.

The two controls are samples around each authored section (`side_samples`) and
stations along the horn axis (`axial_stations`). Test4 was meshed at 2, 5, and
8 kHz while holding every other setting fixed.

| STL seed | Maximum frequency | Time | BEM vertices | Maximum aspect | Surface area | Enclosed volume |
|---:|---:|---:|---:|---:|---:|---:|
| 12×12 | 2 kHz | 4.76 s | 3,518 | 32.62 | 0.446377 m² | 0.002062295 m³ |
| 12×16 | 2 kHz | 1.97 s | 3,121 | 2.52 | 0.446090 m² | 0.002063259 m³ |
| 12×12 | 5 kHz | 4.99 s | 15,503 | 32.62 | 0.446909 m² | 0.002073612 m³ |
| 12×16 | 5 kHz | 4.89 s | 15,410 | 2.16 | 0.446554 m² | 0.002073491 m³ |
| 12×12 | 8 kHz | 10.55 s | 38,890 | 32.55 | 0.446978 m² | 0.002073746 m³ |
| 12×16 | 8 kHz | 10.70 s | 38,946 | 2.44 | 0.446618 m² | 0.002073784 m³ |

Seeds from 6×6 through 24×24 were also screened at 5 kHz. Seeds below 12
changed enclosed volume materially. Increasing both dimensions above 16 did
not consistently reduce final DOFs or time. A 14-side/16-axial authored shell
failed the closed-volume check, demonstrating that simply increasing STL wire
density is not monotonic or automatically safer with the present exporter.

The selected default is **12 side samples × 16 axial stations**. Relative to
12×12 it removes the poor transition elements, materially improves low-frequency
meshing, and has negligible 8 kHz cost. At 8 kHz the enclosed-volume difference
is 0.0018%, surface-area difference is 0.081%, and driven-source-area difference
is 0.045%.

This is an optimization for the current Test4-style geometry family, not proof
that one tessellation is optimal for every future horn. New topology or profile
features should rerun the same meshing-only audit before accepted sweeps.
