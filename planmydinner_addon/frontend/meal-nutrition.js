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
            <div v-if="info.target_note" class="mn-note">ℹ️ {{ info.target_note }}</div>
        </div>
    `,
    computed: {
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
    },
});

export default MealNutrition;

/** Riga compatta "620 kcal · P 35 · C 70 · G 18". */
export function macroLine(n) {
    if (!n) return '';
    return `${Math.round(n.kcal)} kcal · P ${Math.round(n.protein_g)} · C ${Math.round(n.carbs_g)} · G ${Math.round(n.fat_g)}`;
}
