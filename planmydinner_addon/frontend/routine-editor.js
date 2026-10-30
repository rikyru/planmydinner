import { defineComponent } from 'vue';
import { macroLine } from './meal-nutrition.js?v=4';

/**
 * Editor dei pasti fissi (colazione e spuntini): usato nelle Impostazioni e
 * dal ⚙️ della strip in Oggi. Parte dai pasti già definiti, mostra kcal/macro
 * di ciascuno e quanto pesano sui grassi del giorno; mentre modifichi un pasto
 * ricalcola i valori ingrediente per ingrediente.
 */
const RoutineEditor = defineComponent({
    name: 'RoutineEditor',
    inject: ['toast'],
    props: {
        profileId: { type: String, required: true },
    },
    emits: ['changed'],
    template: `
        <div class="routine-editor">
            <div v-if="loading" class="hint">Caricamento…</div>

            <div v-if="totals" class="routine-totals">
                <div><strong>Ogni giorno, in automatico:</strong> {{ macroLine(totals) }}</div>
                <div v-if="targets.fat_g" class="hint">
                    Grassi dei pasti fissi: <strong :style="{color: totals.fat_g > targets.fat_g * 0.4 ? 'var(--danger)' : 'var(--success)'}">{{ Math.round(totals.fat_g) }} g</strong>
                    su {{ Math.round(targets.fat_g) }} g del giorno ({{ Math.round(totals.fat_g / targets.fat_g * 100) }}%)
                    <span v-if="targets.kcal"> · kcal {{ Math.round(totals.kcal) }} su {{ Math.round(targets.kcal) }} ({{ Math.round(totals.kcal / targets.kcal * 100) }}%)</span>
                </div>
                <div v-if="targets.fat_g && totals.fat_g > targets.fat_g * 0.4" class="hint" style="margin-top:2px;">
                    💡 Restano solo {{ Math.max(0, Math.round(targets.fat_g - totals.fat_g)) }} g di grassi per pranzo, cena ed extra: alleggerire qui conta tutti i giorni.
                </div>
            </div>

            <div v-for="s in slots" :key="s.slot" class="routine-editor__slot">
                <div class="routine-editor__head" @click="toggleEdit(s)">
                    <span>{{ s.icon }}</span>
                    <strong style="flex:1;font-size:13.5px;">{{ s.label }}
                        <span v-if="!s.default_on && s.defined" class="hint" style="font-weight:normal;"> · solo quando lo segni</span>
                    </strong>
                    <span v-if="s.defined" class="hint" style="text-align:right;">{{ s.name }}<br>
                        <span v-if="s.nutrition">{{ macroLine(s.nutrition) }}</span></span>
                    <span v-else class="hint">non definito</span>
                    <span style="color:var(--text-3);">{{ editSlot === s.slot ? '▲' : '✏️' }}</span>
                </div>

                <div v-if="editSlot === s.slot" style="margin-top:10px;display:flex;flex-direction:column;gap:8px;">
                    <div style="display:flex;gap:8px;">
                        <input v-model="editForm.description"
                               placeholder="es. caffè, 2 fette biscottate con marmellata, yogurt greco"
                               :disabled="analyzing" @keyup.enter="analyzeDescription">
                        <button @click="analyzeDescription" class="btn-primary btn-sm"
                                :disabled="analyzing || editForm.description.trim().length < 3" style="flex-shrink:0;"
                                title="Struttura il testo che hai scritto">
                            {{ analyzing ? '…' : '✨' }}
                        </button>
                    </div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                        <button @click="suggestMeal(s, false)" class="btn-secondary btn-sm" :disabled="suggesting"
                                title="Proponi una nuova idea con l'AI">
                            {{ suggesting ? 'Proposta…' : '🍳 Proponi' }}
                        </button>
                        <button @click="suggestMeal(s, true)" class="btn-secondary btn-sm" :disabled="suggesting"
                                title="Proponi usando ciò che hai in dispensa">
                            {{ suggesting ? '…' : '🧺 Dalla dispensa' }}
                        </button>
                    </div>
                    <select v-model="pantryPick" @change="addFromPantry" @focus="loadPantry">
                        <option value="">📦 Aggiungi un ingrediente dalla dispensa…</option>
                        <option v-for="p in pantryChoices" :key="p.id" :value="p.id">{{ pantryLabel(p) }}</option>
                    </select>
                    <input v-model="editForm.name" placeholder="Nome (es. Colazione tipo)">
                    <div v-for="(ing, idx) in editForm.ingredients" :key="idx"
                         style="display:grid;grid-template-columns:1fr 70px 90px auto;gap:8px;align-items:center;">
                        <input v-model="ing.name" @change="schedulePreview" :readonly="!!ing.pantry_id"
                               :title="ing.pantry_id ? 'dalla dispensa: valori da etichetta' : ''"
                               :style="ing.pantry_id ? 'background:var(--surface-2, transparent);' : ''">
                        <input v-model.number="ing.grams" type="number" min="0" step="5" @input="schedulePreview">
                        <span class="hint" style="white-space:nowrap;" :style="ingFat(idx) >= 5 ? 'color:var(--danger);font-weight:600;' : ''">{{ ingLine(idx) }}</span>
                        <button @click="removeIngredient(idx)" class="btn-secondary btn-sm">✕</button>
                    </div>
                    <button @click="addIngredient" class="btn-secondary btn-sm" style="align-self:flex-start;">+ ingrediente</button>
                    <div class="routine-editor__preview">
                        <template v-if="previewing">Calcolo…</template>
                        <template v-else-if="preview && preview.nutrition">
                            Totale: <strong>{{ macroLine(preview.nutrition) }}</strong>
                            <span v-if="s.nutrition"> · prima {{ Math.round(s.nutrition.kcal) }} kcal, G {{ Math.round(s.nutrition.fat_g) }}
                                <strong :style="{color: deltaFat(s) > 0 ? 'var(--danger)' : 'var(--success)'}">({{ deltaFat(s) > 0 ? '+' : '' }}{{ deltaFat(s) }} g grassi)</strong></span>
                        </template>
                        <template v-else>Aggiungi gli ingredienti con i grammi per vedere i valori.</template>
                    </div>
                    <label class="toggle-label">
                        <input type="checkbox" v-model="editForm.default_on" style="width:auto;">
                        Conta ogni giorno automaticamente
                    </label>
                    <div style="display:flex;gap:8px;">
                        <button @click="saveSlot(s)" class="btn-primary btn-sm"
                                :disabled="saving || !editForm.name || !editForm.ingredients.length">
                            {{ saving ? 'Salvataggio…' : '💾 Salva' }}
                        </button>
                        <button @click="editSlot = null" class="btn-secondary btn-sm">Annulla</button>
                        <button v-if="s.defined" @click="deleteSlot(s)" class="btn-danger btn-sm" style="margin-left:auto;">🗑️</button>
                    </div>
                    <div v-if="editError" class="error">{{ editError }}</div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            slots: [],
            loading: false,
            targets: {},
            editSlot: null,
            editForm: { description: '', name: '', ingredients: [], default_on: true },
            preview: null,
            previewing: false,
            previewTimer: null,
            suggesting: false,
            analyzing: false,
            saving: false,
            editError: null,
            pantryItems: null,
            pantryPick: '',
        };
    },
    computed: {
        pantryChoices() {
            return (this.pantryItems || []).slice().sort((a, b) => a.name.localeCompare(b.name));
        },
        totals() {
            // ciò che viene contato ogni giorno senza registrarlo
            const on = this.slots.filter(s => s.defined && s.default_on && s.nutrition);
            if (!on.length) return null;
            const t = { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0 };
            for (const s of on) for (const k in t) t[k] += s.nutrition[k] || 0;
            return t;
        },
    },
    mounted() { this.load(); this.loadTargets(); },
    watch: { profileId() { this.load(); this.loadTargets(); } },
    methods: {
        macroLine,
        async load() {
            this.loading = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/routine/?' + params);
                this.slots = resp.ok ? (await resp.json()).slots : [];
            } catch (_) {
                this.slots = [];
            } finally {
                this.loading = false;
            }
        },
        async loadTargets() {
            try {
                const today = new Date().toISOString().slice(0, 10);
                const params = new URLSearchParams({ profile_id: this.profileId, start_date: today, end_date: today });
                const resp = await window.apiFetch('/integration/summary?' + params);
                this.targets = resp.ok ? ((await resp.json()).targets || {}) : {};
            } catch (_) { this.targets = {}; }
        },
        toggleEdit(s) {
            if (this.editSlot === s.slot) { this.editSlot = null; return; }
            this.editSlot = s.slot;
            this.editError = null;
            this.preview = null;
            this.editForm = {
                description: '',
                name: s.name || '',
                ingredients: (s.ingredients || []).map(i => ({ ...i })),
                default_on: s.default_on,
            };
            this.runPreview();
        },
        pantryLabel(p) {
            const n = p.nutrition;
            if (!n || n.kcal == null) return p.name + ' · (senza valori)';
            return p.name + ' · ' + Math.round(n.kcal) + ' kcal, G ' + Math.round(n.fat_g || 0) + ' /100g';
        },
        async loadPantry() {
            if (this.pantryItems) return;
            try {
                const resp = await window.apiFetch('/pantry/items?limit=500');
                this.pantryItems = resp.ok ? await resp.json() : [];
            } catch (_) {
                this.pantryItems = [];
            }
        },
        // prodotto della dispensa -> riga ingrediente; i grammi partono da 30 (da
        // correggere), i valori sono quelli per 100 g dell'etichetta
        addFromPantry() {
            const p = (this.pantryItems || []).find(x => x.id === this.pantryPick);
            this.pantryPick = '';
            if (!p) return;
            const per100 = p.nutrition && p.nutrition.kcal != null ? p.nutrition : null;
            const rows = this.editForm.ingredients.filter(i => (i.name || '').trim());
            rows.push({ name: p.name, food_group: 'altro', grams: 30,
                        pantry_id: per100 ? p.id : null, per_100g: per100 });
            this.editForm.ingredients = rows;
            if (!this.editForm.name) this.editForm.name = p.name;
            this.runPreview();
        },
        ingPayload(i) {
            const row = { name: i.name.trim(), food_group: i.food_group || 'altro', grams: i.grams };
            if (i.pantry_id) { row.pantry_id = i.pantry_id; row.per_100g = i.per_100g || null; }
            return row;
        },
        addIngredient() {
            this.editForm.ingredients.push({ name: '', food_group: 'altro', grams: 50 });
        },
        removeIngredient(idx) {
            this.editForm.ingredients.splice(idx, 1);
            this.schedulePreview();
        },
        schedulePreview() {
            clearTimeout(this.previewTimer);
            this.previewTimer = setTimeout(() => this.runPreview(), 700);
        },
        async runPreview() {
            const ingredients = this.editForm.ingredients
                .filter(i => (i.name || '').trim() && i.grams > 0)
                .map(i => this.ingPayload(i));
            if (!ingredients.length) { this.preview = null; return; }
            this.previewing = true;
            try {
                const resp = await window.apiFetch('/routine/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ profile_id: this.profileId, ingredients }),
                });
                this.preview = resp.ok ? await resp.json() : null;
            } catch (_) {
                this.preview = null;
            } finally {
                this.previewing = false;
            }
        },
        previewRow(idx) {
            const ing = this.editForm.ingredients[idx];
            if (!this.preview || !ing) return null;
            const name = (ing.name || '').trim();
            return (this.preview.ingredients || []).find(r => r.name === name && r.grams === ing.grams) || null;
        },
        ingFat(idx) {
            const r = this.previewRow(idx);
            return r && r.known ? r.fat_g : 0;
        },
        ingLine(idx) {
            const r = this.previewRow(idx);
            if (!r) return '';
            if (!r.known) return 'sconosciuto';
            const ing = this.editForm.ingredients[idx];
            return (ing && ing.pantry_id ? '📦 ' : '') + Math.round(r.kcal) + ' kcal · G ' + Math.round(r.fat_g);
        },
        deltaFat(s) {
            if (!this.preview || !this.preview.nutrition || !s.nutrition) return 0;
            return Math.round(this.preview.nutrition.fat_g - s.nutrition.fat_g);
        },
        async analyzeDescription() {
            const description = this.editForm.description.trim();
            if (description.length < 3) return;
            this.analyzing = true;
            this.editError = null;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/consumed-entries/text/analyze?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ description }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'Analisi fallita.');
                }
                const proposal = await resp.json();
                this.editForm.name = this.editForm.name || proposal.name;
                this.editForm.ingredients = proposal.ingredients;
                this.runPreview();
            } catch (e) {
                this.editError = e.message;
            } finally {
                this.analyzing = false;
            }
        },
        async suggestMeal(s, fromPantry = false) {
            this.suggesting = true;
            try {
                const params = new URLSearchParams({ slot: s.slot });
                // evita di riproporre il pasto attuale (varietà)
                const cur = s.name || this.editForm.name;
                if (cur) params.set('avoid', cur);
                if (fromPantry) params.set('from_pantry', 'true');
                const resp = await window.apiFetch('/routine/suggest?' + params);
                if (!resp.ok) throw new Error((await resp.json()).detail || 'errore');
                const p = await resp.json();
                this.editForm.name = p.name || this.editForm.name;
                this.editForm.ingredients = p.ingredients || [];
                this.runPreview();
                this.toast.add(fromPantry ? 'Proposta dalla dispensa: rivedi e salva'
                                          : 'Proposta pronta: rivedi e salva', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.suggesting = false;
            }
        },
        async saveSlot(s) {
            this.saving = true;
            this.editError = null;
            try {
                const body = {
                    profile_id: this.profileId,
                    name: this.editForm.name,
                    ingredients: this.editForm.ingredients.filter(i => (i.name || '').trim() && i.grams > 0)
                        .map(i => this.ingPayload(i)),
                    default_on: this.editForm.default_on,
                };
                const resp = await window.apiFetch('/routine/' + s.slot, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add(s.label + ' salvata!', 'success');
                this.editSlot = null;
                await this.load();
                this.$emit('changed');
            } catch (e) {
                this.editError = 'Errore: ' + e.message;
            } finally {
                this.saving = false;
            }
        },
        async deleteSlot(s) {
            if (!confirm('Rimuovere "' + s.name + '" da ' + s.label + '?')) return;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/routine/' + s.slot + '?' + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.editSlot = null;
                await this.load();
                this.$emit('changed');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
    },
});

export default RoutineEditor;
