import { defineComponent } from 'vue';

/**
 * "Simula un pasto": prima di decidere (mensa, ristorante, take-away) vedi
 * come chiude la giornata e quanto resta per l'altro pasto. Due modi:
 *  - "Cosa mangio": descrizione libera o pasto salvato -> bilancio;
 *  - "Consigliami": dove mangi (es. cinese) -> 3 ordini dimensionati sulla quota.
 * "Mettilo nel piano" / "Pasto libero" lo mettono nello slot SENZA segnarlo
 * mangiato: lo si registra dopo, come ogni pasto del piano.
 * Eventi: 'saved' dopo la registrazione, 'close'.
 */
const LEVEL_CLASS = { ok: 'sim-ok', under: 'sim-ok', over: 'sim-warn', way_over: 'sim-bad', unknown: '' };

const SimulateModal = defineComponent({
    name: 'SimulateModal',
    inject: ['toast'],
    props: {
        profileId: { type: String, required: true },
        profileBId: { type: String, default: null },
        mealType: { type: String, default: 'cena' },
        mealDate: { type: String, required: true },
    },
    emits: ['close', 'saved'],
    template: `
        <div class="modal-overlay" @click.self="$emit('close')">
            <div class="modal sim-modal">
                <h3>🧮 Simula un pasto</h3>
                <div class="sim-row sim-slots">
                    <span class="sim-label">Per</span>
                    <button v-for="t in ['pranzo', 'cena']" :key="t" class="chip"
                            :class="{ 'chip--on': slot === t }" @click="setSlot(t)">{{ t }}</button>
                </div>
                <div class="sim-row">
                    <button class="chip" :class="{ 'chip--on': mode === 'eat' }" @click="mode = 'eat'">Cosa mangio</button>
                    <button class="chip" :class="{ 'chip--on': mode === 'advice' }" @click="mode = 'advice'">Consigliami cosa prendere</button>
                </div>

                <!-- Cosa mangio: descrizione o pasto salvato -->
                <div v-if="mode === 'eat'">
                    <div class="sim-input">
                        <input v-model="description" :disabled="busy" @keyup.enter="simulateText"
                               placeholder="es. lasagne e cotoletta in mensa, involtini + riso cantonese">
                        <button class="btn-primary" :disabled="busy || description.trim().length < 3"
                                @click="simulateText">{{ busy ? '…' : 'Simula' }}</button>
                    </div>
                    <div v-if="saved.length && !result" class="sim-saved">
                        <div class="sim-hint">oppure un pasto salvato:</div>
                        <button v-for="m in saved.slice(0, 8)" :key="m.id" class="chip" :disabled="busy"
                                @click="simulateSaved(m)">{{ m.name }}<span v-if="m.nutrition"> · {{ Math.round(m.nutrition.kcal) }}</span></button>
                    </div>
                </div>

                <!-- Consigliami -->
                <div v-else>
                    <div class="sim-input">
                        <input v-model="place" :disabled="busy" @keyup.enter="suggest"
                               placeholder="es. cinese, pizzeria, sushi, kebab, mensa con primi e secondi">
                        <button class="btn-primary" :disabled="busy || place.trim().length < 2"
                                @click="suggest">{{ busy ? '…' : 'Consigli' }}</button>
                    </div>
                    <input v-model="notes" class="sim-notes" :disabled="busy"
                           placeholder="note facoltative (es. ho molta fame, niente fritto)">
                    <div v-if="advice" class="sim-advice">
                        <div class="sim-hint">Quota per {{ slot }}: ~{{ advice.quota_kcal }} kcal, ~{{ advice.protein_quota_g }} g proteine</div>
                        <div v-for="(o, i) in advice.options" :key="i" class="recipe-option sim-option"
                             :class="{ 'sim-picked': result === o }" @click="result = o">
                            <strong>{{ o.name }}</strong>
                            <span><b :class="levelClass(o)">~{{ o.meal.kcal }} kcal</b> · P {{ o.meal.protein_g }} g · C {{ o.meal.carbs_g }} g · G {{ o.meal.fat_g }} g</span>
                            <span v-if="o.why">{{ o.why }}</span>
                        </div>
                        <div v-if="advice.avoid.length" class="sim-hint">Da evitare: {{ advice.avoid.join(', ') }}</div>
                        <ul v-if="advice.tips.length" class="sim-tips"><li v-for="t in advice.tips" :key="t">{{ t }}</li></ul>
                    </div>
                </div>

                <div v-if="error" class="error">{{ error }}</div>

                <!-- Bilancio -->
                <div v-if="result" class="sim-result" :class="levelClass(result)">
                    <div class="sim-head">
                        <strong>{{ result.name }}</strong>
                        <span class="sim-badge">{{ result.verdict.text || '' }}</span>
                    </div>
                    <div class="sim-macros">~{{ result.meal.kcal }} kcal · P {{ result.meal.protein_g }} g · C {{ result.meal.carbs_g }} g · G {{ result.meal.fat_g }} g
                        <span v-if="result.protein_quota_g && result.meal.protein_g < result.protein_quota_g * 0.7" class="sim-hint"> · poche proteine (quota ~{{ result.protein_quota_g }} g)</span>
                    </div>
                    <div v-if="result.target" class="sim-bar" :title="result.day_total + ' / ' + result.target.kcal + ' kcal'">
                        <span class="sim-seg sim-fixed" :style="seg(result.fixed_kcal)" title="colazione/spuntini/extra"></span>
                        <span class="sim-seg sim-meal" :style="seg(result.meal.kcal)" :title="slot"></span>
                        <span v-if="result.other.day_kcal" class="sim-seg sim-other" :class="{ 'sim-assumed': result.other.assumed }" :style="seg(result.other.day_kcal)" :title="result.other.meal_type"></span>
                        <span class="sim-target" :style="{ left: Math.min(100, result.target.kcal / scaleMax * 100) + '%' }"></span>
                    </div>
                    <div v-if="result.target" class="sim-legend">
                        <span><i class="sim-fixed"></i>fissi {{ result.fixed_kcal }}</span>
                        <span><i class="sim-meal"></i>{{ slot }} {{ result.meal.kcal }}</span>
                        <span v-if="result.other.day_kcal"><i class="sim-other" :class="{ 'sim-assumed': result.other.assumed }"></i>{{ result.other.meal_type }} {{ result.other.day_kcal }}{{ result.other.consumed ? '' : result.other.assumed ? ' (stima: quota)' : ' (previsto)' }}</span>
                        <span>| obiettivo {{ result.target.kcal }}</span>
                    </div>
                    <table v-if="result.macros && result.macros.length" class="sim-macro-table">
                        <thead><tr><th></th><th>pasto</th><th>giornata</th><th>obiettivo</th><th></th></tr></thead>
                        <tbody>
                            <tr v-for="m in result.macros" :key="m.key" :class="'sim-m-' + m.status">
                                <td>{{ m.label }}</td><td>{{ m.meal }} g</td><td><strong>{{ m.total }} g</strong></td>
                                <td>{{ m.target }} g</td>
                                <td class="sim-m-bar"><div class="sim-m-wrap"><div class="sim-m-track"><span :style="{ width: Math.min(m.pct, 150) / 1.5 + '%' }"></span><i></i></div><em>{{ m.pct }}%</em></div></td>
                            </tr>
                        </tbody>
                    </table>
                    <ul class="sim-lines"><li v-for="l in (result.verdict.lines || [result.verdict.text])" :key="l">{{ l }}</li></ul>

                    <details class="sim-ings">
                        <summary>Ingredienti stimati ({{ result.ingredients.length }}) — correggi i grammi</summary>
                        <div v-for="(ing, idx) in result.ingredients" :key="idx" class="custom-row">
                            <input v-model="ing.name" style="flex:2">
                            <input v-model.number="ing.grams" type="number" min="0" step="10" style="width:80px">
                            <button @click="result.ingredients.splice(idx, 1)" class="btn-secondary">✕</button>
                        </div>
                        <button class="btn-secondary" :disabled="busy" @click="recompute">↻ Ricalcola</button>
                    </details>

                    <div class="sim-actions">
                        <button class="btn-consumed" :disabled="busy" @click="take(false)">📅 Mettilo a {{ slot }}</button>
                        <button class="btn-free" :disabled="busy" @click="take(true)">🎉 Come pasto libero</button>
                        <button class="btn-secondary" @click="result = null">↩ Prova altro</button>
                    </div>
                </div>

                <button @click="$emit('close')" class="btn-secondary" style="margin-top:12px;">Chiudi</button>
            </div>
        </div>
    `,
    data() {
        return { slot: this.mealType || 'cena', mode: 'eat', description: '', place: '', notes: '',
                 busy: false, error: null, result: null, advice: null, saved: [] };
    },
    computed: {
        scaleMax() {
            const r = this.result;
            if (!r || !r.target) return 1;
            return Math.max(r.target.kcal, r.fixed_kcal + r.meal.kcal + (r.other.day_kcal || 0)) * 1.05;
        },
    },
    mounted() { this.loadSaved(); },
    methods: {
        levelClass(r) { return LEVEL_CLASS[r?.verdict?.level] || ''; },
        seg(kcal) { return { width: Math.max(0, kcal / this.scaleMax * 100) + '%' }; },
        params() {
            return new URLSearchParams({ profile_id: this.profileId, meal_type: this.slot, target_date: this.mealDate });
        },
        async post(path, body) {
            this.busy = true;
            this.error = null;
            try {
                const resp = await window.apiFetch(path + '?' + this.params(), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                const j = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(j.detail || 'Errore');
                return j;
            } catch (e) {
                this.error = e.message;
                return null;
            } finally {
                this.busy = false;
            }
        },
        async loadSaved() {
            try {
                const resp = await window.apiFetch('/consumed-entries/mensa?' + new URLSearchParams({ profile_id: this.profileId }));
                this.saved = resp.ok ? await resp.json() : [];
            } catch (_) { this.saved = []; }
        },
        async setSlot(t) {
            if (this.slot === t) return;
            this.slot = t;
            // stesso pasto, altro slot: ricalcola il bilancio (senza LLM)
            if (this.advice && this.place.trim()) { this.result = null; await this.suggest(); }
            else if (this.result) await this.recompute();
        },
        async simulateText() {
            const description = this.description.trim();
            if (description.length < 3) return;
            const r = await this.post('/simulate/meal', { description });
            if (r) this.result = r;
        },
        async simulateSaved(m) {
            const r = await this.post('/simulate/meal', { candidate_id: m.id });
            if (r) this.result = r;
        },
        async recompute() {
            const cur = this.result;
            const r = await this.post('/simulate/meal', {
                name: cur.name, ingredients: cur.ingredients.filter(i => i.name && i.grams > 0) });
            if (r) {
                if (this.advice) {
                    const i = this.advice.options.indexOf(cur);
                    if (i >= 0) this.advice.options.splice(i, 1, Object.assign(r, { why: cur.why }));
                }
                this.result = r;
            }
        },
        async suggest() {
            const place = this.place.trim();
            if (place.length < 2) return;
            this.result = null;
            const r = await this.post('/simulate/suggest', { place, notes: this.notes.trim() });
            if (r) this.advice = r;
        },
        async take(asFree) {
            // nel piano ma NON consumato: si segna mangiato dopo, come gli altri pasti
            const r = this.result;
            this.busy = true;
            this.error = null;
            try {
                const resp = await window.apiFetch('/simulate/choose?' + this.params(), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: r.name, as_free_meal: asFree, profile_id_B: this.profileBId,
                                           ingredients: r.ingredients.filter(i => i.name && i.grams > 0) }) });
                const j = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(j.detail || 'Errore');
                this.toast.add(`"${r.name}" messo a ${this.slot}${asFree ? ' come pasto libero' : ''} (da segnare quando lo mangi)`, 'success');
                this.$emit('saved');
                this.$emit('close');
            } catch (e) {
                this.error = 'Errore nel salvataggio: ' + e.message;
            } finally {
                this.busy = false;
            }
        },
    },
});

export default SimulateModal;
