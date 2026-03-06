# Classificazione Food Groups — Note di Implementazione

## Il problema: dual naming di carne bianca

Il sistema usa **due nomi diversi** per le carni bianche a seconda del contesto:

| Contesto | Nome usato |
|---|---|
| `frequency_targets` (PlanRules, input utente) | `carne_bianca` |
| `protein_sequence`, `protein_cat_counts`, `protein_cat_limits` | `carne_bianca` |
| `food_group` negli ingredienti delle ricette (legacy) | `pollo` |
| `food_group` negli ingredienti generati post-fix 2026-03 | `carne_bianca` |

**Sintomo**: i limiti settimanali su `carne_bianca` non venivano mai applicati perché il confronto nei rotation rules era `"pollo" != "carne_bianca"`.

## La fix (2026-03-07)

### 1. `_PROTEIN_CATEGORY_MAP` aggiornato

```python
_PROTEIN_CATEGORY_MAP = {
    "pollo":        "carne_bianca",   # legacy food_group
    "carne_bianca": "carne_bianca",   # canonical — ora riconosciuto direttamente
    "carne_rossa":  "carne_rossa",
    "pesce":        "pesce",
    "legumi":       "legumi",
    "proteina":     "proteina",
    "proteine":     "proteina",
}
```

### 2. `_PROTEIN_GROUPS` aggiornato

```python
_PROTEIN_GROUPS = {"proteina", "pollo", "carne_bianca", "pesce", "carne_rossa", "legumi"}
```

### 3. `_filter_hard_constraints` — rotation rule check

Prima: confronto diretto `normalize(food_group) == normalize(rule)`.
Dopo: risoluzione canonica via `_PROTEIN_CATEGORY_MAP` per entrambi i lati:
```python
rec_fg_cat = _PROTEIN_CATEGORY_MAP.get(rec_fg, rec_fg)
rule_fg_cat = _PROTEIN_CATEGORY_MAP.get(normalized_rule_fg, normalized_rule_fg)
if rec_fg == normalized_rule_fg or rec_fg_cat == rule_fg_cat or name == rule:
```

### 4. Consumption counting in `_filter_hard_constraints`

Il conteggio dei pasti consumati ora canonicalizza il food_group prima di incrementare:
```python
cat = _PROTEIN_CATEGORY_MAP.get(food_group, food_group)
consumption_counts[cat] += 1
```
Così se si consuma una ricetta con `food_group="pollo"`, il contatore `"carne_bianca"` si aggiorna.

### 5. `_get_food_group_for_item` (keyword lookup)

Prima: `"pollo"` → `"pollo"`
Dopo: `"pollo"`, `"petto di pollo"`, `"tacchino"`, ecc. → `"carne_bianca"` (canonico)

Aggiunto anche `maiale`, `vitellone`, `bovino`, `agnello`, `cinghiale` → `"carne_rossa"`.
Aggiunto `sgombro`, `orata`, `spigola` → `"pesce"`.
Aggiunto `piselli`, `fave` → `"legumi"`.

### 6. `_FG_KEYWORDS` in `_generate_from_plan_rules`

Post-fix del food_group dopo generazione LLM: ora usa `"carne_bianca"` invece di `"pollo"`.

### 7. `_cat_to_fg` in `_rules_to_planned_meal`

```python
"carne_bianca": "carne_bianca"  # era "pollo"
```

## Regola da seguire in futuro

- Il `food_group` canonico per carni bianche è **`carne_bianca`** (non `"pollo"`).
- `"pollo"` rimane nella mappa come alias legacy per retrocompatibilità con ricette esistenti nel DB.
- Quando si creano nuove ricette (manualmente o via LLM), usare `"carne_bianca"` come food_group.

## Food groups riconosciuti

| `food_group` | Categoria proteica | Note |
|---|---|---|
| `carne_bianca` | `carne_bianca` | canonical |
| `pollo` | `carne_bianca` | legacy alias |
| `carne_rossa` | `carne_rossa` | |
| `pesce` | `pesce` | |
| `legumi` | `legumi` | |
| `proteina` | `proteina` | uova, tofu, generico |
| `carboidrati` | — | non proteina |
| `verdure` | — | non proteina |
