import { defineComponent } from 'vue';

/**
 * Valori nutrizionali di un pasto (kcal + macro) confrontati con l'obiettivo
 * del pasto, più i suggerimenti per centrarlo. `info` è una voce di
 * days[].meals da GET /integration/summary?meal_detail=true.
 */
const MACROS = [
    { key: 'kcal',      label: 'kcal',      unit: '' },
    { key: 'protein_g', label: 'Proteine',  unit: 'g' },
    { key: 'carbs_g',   label: 'Carbo',     unit: 'g' },
    { key: 'fat_g',     label: 'Grassi',    unit: 'g' },
];

const TIP_ICONS = { fat: '🫒', kcal_high: '⬇️', kcal_low: '⬆️', carbs: '🌾', protein: '🥩' };

const MealNutrition = defineComponent({
    name: 'MealNutrition',
    props: {
        info: { type: Object, required: true },
        compact: { type: Boolean, default: false },
    },
    template: `
        <div class="meal-nutrition" :class="{ 'meal-nutrition--compact': compact }">
            <div class="mn-grid">
                <div v-for="m in rows" :key="m.key" class="mn-cell" :class="'mn-cell--' + m.status">
                    <span class="mn-value">{{ m.value }}<small>{{ m.unit }}</small></span>
                    <span class="mn-label">{{ m.label }}<template v-if="m.target"> / {{ m.target }}{{ m.unit }}</template></span>
                    <span v-if="m.target" class="mn-bar"><span :style="{ width: m.pct + '%' }"></span></span>
                </div>
            </div>
            <div v-if="info.estimated" class="hint" style="margin-top:6px;">Stima del pasto libero.</div>
            <div v-if="adaptChanges.length" class="mn-adapt">
                ⚖️ <strong>Porzioni di oggi</strong> (piano nutrizionista + quota):
                {{ adaptChanges.join(' · ') }}
            </div>
            <!-- Chi fa sforare la quota -->
            <ul v-if="info.over && info.over.length" class="mn-over">
                <li v-for="o in info.over" :key="o.macro">
                    🔺 <strong>{{ o.label }} oltre la quota</strong> (+{{ fmt(o.excess, o.macro) }}):
                    soprattutto
                    <template v-for="(c, i) in o.culprits" :key="c.name">{{ i ? ', ' : ' ' }}<strong>{{ c.name }}</strong> {{ fmt(c.value, o.macro) }} ({{ c.share }}%)</template>
                </li>
            </ul>
            <!-- Pasto già registrato: bilancio, non consigli a posteriori -->
            <div v-if="info.verdict" class="mn-verdict" :class="info.ok ? 'is-ok' : 'is-off'">
                {{ info.ok ? '✓' : '⚖️' }} {{ info.verdict }}
            </div>
            <ul v-else-if="info.tips && info.tips.length" class="mn-tips">
                <li v-for="(t, i) in info.tips" :key="i">
                    <span class="mn-tip-icon">{{ icon(t.type) }}</span><span>{{ t.text }}</span>
                </li>
            </ul>
            <div v-else-if="info.target && info.ok" class="mn-ok">✓ In linea con la quota del pasto</div>
            <div v-else-if="!info.target && !compact" class="hint" style="margin-top:6px;">
                Imposta un obiettivo giornaliero (📊 Storico) per suggerimenti su misura.
            </div>
            <!-- Dettaglio per ingrediente -->
            <div v-if="info.ingredients && info.ingredients.length" class="mn-ing">
                <button class="mn-ing__toggle" @click="showIngredients = !showIngredients">
                    {{ showIngredients ? '▾' : '▸' }} Valori per ingrediente
                </button>
                <table v-if="showIngredients" class="mn-ing__table">
                    <thead><tr><th>Ingrediente</th><th>g</th><th>kcal</th><th>P</th><th>C</th><th>G</th></tr></thead>
                    <tbody>
                        <tr v-for="ing in info.ingredients" :key="ing.name">
                            <td>{{ ing.name }}<span v-if="ing.estimated" class="mn-est"> stimato</span></td>
                            <td>{{ ing.grams }}</td>
                            <td :class="{ 'mn-hot': isCulprit('kcal', ing.name) }">{{ Math.round(ing.kcal) }}</td>
                            <td>{{ Math.round(ing.protein_g) }}</td>
                            <td :class="{ 'mn-hot': isCulprit('carbs_g', ing.name) }">{{ Math.round(ing.carbs_g) }}</td>
                            <td :class="{ 'mn-hot': isCulprit('fat_g', ing.name) }">{{ Math.round(ing.fat_g) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <div v-if="info.target_note" class="mn-note">ℹ️ {{ info.target_note }}</div>
        </div>
    `,
    data() {
        return { showIngredients: false };
    },
    computed: {
        // adapt_note = ["quota 812 kcal", "Pasta 100 → 85 g", ...]: qui solo i cambi
        adaptChanges() {
            return (this.info.adapt_note || []).filter(n => !n.startsWith('quota'));
        },
        rows() {
            const n = this.info.nutrition || {};
            const t = this.info.target || {};
            return MACROS.map(m => {
                const value = Math.round(n[m.key] || 0);
                const target = t[m.key] ? Math.round(t[m.key]) : null;
                let status = 'none';
                if (target) {
                    const r = value / target;
                    // proteine: conta stare sotto; grassi/kcal: conta stare sopra
                    if (m.key === 'protein_g') status = r < 0.85 ? 'warn' : 'ok';
                    else if (r > 1.1) status = 'warn';
                    else if (r < 0.85 && m.key === 'kcal') status = 'low';
                    else status = 'ok';
                }
                return { ...m, value, target, status,
                         pct: target ? Math.min(100, Math.round(value / target * 100)) : 0 };
            });
        },
    },
    methods: {
        icon(type) { return TIP_ICONS[type] || '💡'; },
        fmt(v, macro) { return Math.round(v) + (macro === 'kcal' ? ' kcal' : ' g'); },
        isCulprit(macro, name) {
            const o = (this.info.over || []).find(x => x.macro === macro);
            return !!(o && o.culprits.some(c => c.name === name));
        },
    },
});

export default MealNutrition;

/**
 * Fattore di porzione di un ingrediente in un pasto del piano: le porzioni
 * adattate per quel giorno (item.portions) o, in mancanza, il vecchio `scale`
 * sui soli carboidrati. Stessa regola del backend (nutrition.portion_factor).
 */
export function portionFactor(item, meal, ingredient) {
    const portions = item && item.portions;
    if (portions) return portions[(ingredient.name || '').trim().toLowerCase()] ?? 1;
    const fg = (ingredient.food_group || '').trim().toLowerCase();
    return (fg === 'carboidrati' || fg === 'carboidrato') ? ((meal && meal.scale) || 1) : 1;
}

/** Riga compatta "620 kcal · P 35 · C 70 · G 18". */
export function macroLine(n) {
    if (!n) return '';
    return `${Math.round(n.kcal)} kcal · P ${Math.round(n.protein_g)} · C ${Math.round(n.carbs_g)} · G ${Math.round(n.fat_g)}`;
}
