# Structured layout search (Optuna, routed, 3 seeds)

## attention_layer (32 trials)

| parameter | Spearman vs CPD gain | Spearman vs WL gain |
|---|---|---|
| dsp_on_l0 | -0.38 | -0.30 |
| bram_on_l0 | +0.32 | -0.13 |
| cluster | -0.56 | -0.27 |
| stagger | -0.13 | +0.31 |
| band_pos | -0.24 | +0.23 |
| imbalance(dsp) | -0.15 | -0.34 |

Top trials (sum of CPD + WL gain vs aligned reference, 3 seeds):

| trial | dsp_on_l0 | bram_on_l0 | cluster | stagger | band_pos | CPD % | WL % |
|---|---|---|---|---|---|---|---|
| 40 | 5 | 12 | 0.23 | 0.20 | 0.77 | +3.56 | +1.89 |
| 62 | 7 | 13 | 0.46 | 0.59 | 0.60 | +1.23 | +2.85 |
| 66 | 5 | 10 | 0.32 | 0.20 | 0.81 | +2.61 | +1.39 |

## stereovision1 (45 trials)

| parameter | Spearman vs CPD gain | Spearman vs WL gain |
|---|---|---|
| dsp_on_l0 | -0.10 | -0.04 |
| bram_on_l0 | +0.21 | +0.22 |
| cluster | -0.13 | -0.57 |
| stagger | +0.02 | +0.01 |
| band_pos | -0.06 | -0.05 |
| imbalance(dsp) | -0.09 | -0.36 |

Top trials (sum of CPD + WL gain vs aligned reference, 3 seeds):

| trial | dsp_on_l0 | bram_on_l0 | cluster | stagger | band_pos | CPD % | WL % |
|---|---|---|---|---|---|---|---|
| 45 | 5 | 11 | 0.49 | 0.32 | 0.31 | +1.94 | +1.58 |
| 35 | 4 | 9 | 0.38 | 0.35 | 0.55 | +1.14 | +1.86 |
| 42 | 1 | 11 | 0.35 | 0.34 | 0.31 | +1.37 | +0.98 |

## tpu_like_small_os (44 trials)

| parameter | Spearman vs CPD gain | Spearman vs WL gain |
|---|---|---|
| dsp_on_l0 | -0.15 | -0.06 |
| bram_on_l0 | +0.32 | +0.58 |
| cluster | -0.35 | -0.79 |
| stagger | -0.26 | -0.48 |
| band_pos | -0.04 | +0.30 |
| imbalance(dsp) | -0.38 | -0.19 |

Top trials (sum of CPD + WL gain vs aligned reference, 3 seeds):

| trial | dsp_on_l0 | bram_on_l0 | cluster | stagger | band_pos | CPD % | WL % |
|---|---|---|---|---|---|---|---|
| 63 | 5 | 16 | 0.00 | 0.04 | 0.59 | -0.11 | +2.21 |
| 46 | 4 | 15 | 0.06 | 0.23 | 0.57 | -1.14 | +1.87 |
| 56 | 4 | 15 | 0.12 | 0.08 | 0.48 | -1.18 | +1.78 |
